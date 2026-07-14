import json
import smtplib
import urllib.request
import urllib.error
import structlog
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import settings

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Severity → emoji mapping for Slack
SEVERITY_EMOJI = {
    "critical": "🚨",
    "high": "🔴",
    "medium": "🟡",
    "low": "🟢",
}

# Default colours for Slack message attachments
SEVERITY_COLOR = {
    "critical": "#a12c7b",
    "high": "#da7101",
    "medium": "#d19900",
    "low": "#437a22",
}


class NotificationService:
    """
    Delivers alerts and reports via Email and Slack.

    Channels:
      - "slack"  → POST to AXIOM_SLACK_WEBHOOK_URL (settings)
      - "email"  → SMTP using AXIOM_SMTP_* settings
      - "both"   → sends to both channels

    All methods return {"sent": True, "channels": [...]} or {"error": "..."}
    — never raise inside this module.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. High-level: send_alert (incident / pipeline / freshness alerts)
    # ------------------------------------------------------------------

    async def send_alert(
        self,
        channel: str,
        message: str,
        severity: str = "medium",
        title: str = "AXIOM Alert",
        metadata: dict | None = None,
    ) -> dict:
        """
        Sends a structured alert to the specified channel.

        Args:
            channel:  "slack" | "email" | "both"
            message:  alert body text
            severity: "low" | "medium" | "high" | "critical"
            title:    alert heading
            metadata: extra key-value pairs appended to the message

        Returns:
          { "sent": True/False, "channels": [...], "errors": {...} }
        """
        log.info(
            "notification.send_alert",
            tenant_id=self.tenant_id,
            channel=channel,
            severity=severity,
            title=title,
        )

        channels_sent = []
        errors = {}

        emoji = SEVERITY_EMOJI.get(severity, "⚪")
        full_title = f"{emoji} [{severity.upper()}] {title}"

        if channel in ("slack", "both"):
            result = await self.send_slack(
                message=message,
                title=full_title,
                severity=severity,
                metadata=metadata,
            )
            if "error" in result:
                errors["slack"] = result["error"]
            else:
                channels_sent.append("slack")

        if channel in ("email", "both"):
            to_address = getattr(settings, "AXIOM_ALERT_EMAIL", None)
            if to_address:
                body = self._format_email_body(
                    title=full_title,
                    message=message,
                    severity=severity,
                    metadata=metadata,
                )
                result = await self.send_email(
                    to=to_address,
                    subject=full_title,
                    body=body,
                    html=True,
                )
                if "error" in result:
                    errors["email"] = result["error"]
                else:
                    channels_sent.append("email")
            else:
                log.warning("notification.send_alert.no_email_configured")

        return {
            "sent": len(channels_sent) > 0,
            "channels": channels_sent,
            "errors": errors if errors else None,
        }

    # ------------------------------------------------------------------
    # 2. send_slack
    # ------------------------------------------------------------------

    async def send_slack(
        self,
        message: str,
        title: str = "AXIOM Notification",
        channel: str | None = None,
        severity: str = "medium",
        metadata: dict | None = None,
    ) -> dict:
        """
        Posts a message to Slack via incoming webhook.

        Reads webhook URL from: settings.AXIOM_SLACK_WEBHOOK_URL
        Reads default channel from: settings.AXIOM_SLACK_CHANNEL (optional)

        Constructs a Slack Block Kit payload with:
          - Header block
          - Body section
          - Metadata fields (if provided)
          - Colored attachment border for severity

        Returns: { "sent": True } or { "error": "..." }
        """
        webhook_url = getattr(settings, "AXIOM_SLACK_WEBHOOK_URL", None)
        if not webhook_url:
            log.warning("notification.send_slack.no_webhook_configured")
            return {"error": "AXIOM_SLACK_WEBHOOK_URL is not configured"}

        try:
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title[:150], "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
            ]

            if metadata:
                fields = [
                    {"type": "mrkdwn", "text": f"*{k}:*\n{v}"}
                    for k, v in metadata.items()
                ]
                # Slack limits to 10 fields per section
                blocks.append({"type": "section", "fields": fields[:10]})

            blocks.append({"type": "divider"})
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"AXIOM DataOps | {utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                    }
                ],
            })

            payload = {
                "attachments": [
                    {
                        "color": SEVERITY_COLOR.get(severity, "#888888"),
                        "blocks": blocks,
                    }
                ]
            }

            if channel:
                payload["channel"] = channel
            elif hasattr(settings, "AXIOM_SLACK_CHANNEL"):
                payload["channel"] = settings.AXIOM_SLACK_CHANNEL

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    log.info("notification.send_slack.ok", title=title)
                    return {"sent": True, "channel": channel}
                else:
                    body = resp.read().decode()
                    return {"error": f"Slack responded {resp.status}: {body}"}

        except urllib.error.URLError as exc:
            log.error("notification.send_slack.url_error", error=str(exc))
            return {"error": f"Slack webhook request failed: {str(exc)}"}
        except Exception as exc:
            log.error("notification.send_slack.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. send_email
    # ------------------------------------------------------------------

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = True,
        cc: list[str] | None = None,
    ) -> dict:
        """
        Sends an email via SMTP.

        Reads config from settings:
          AXIOM_SMTP_HOST       (default: localhost)
          AXIOM_SMTP_PORT       (default: 587)
          AXIOM_SMTP_USER       (optional — skip auth if missing)
          AXIOM_SMTP_PASSWORD   (optional)
          AXIOM_SMTP_FROM       (default: axiom@dataops.ai)
          AXIOM_SMTP_USE_TLS    (default: True)

        Args:
            to:      recipient email address
            subject: email subject line
            body:    email body (HTML or plain text)
            html:    True = Content-Type text/html, False = text/plain
            cc:      optional CC addresses

        Returns: { "sent": True } or { "error": "..." }
        """
        host = getattr(settings, "AXIOM_SMTP_HOST", "localhost")
        port = int(getattr(settings, "AXIOM_SMTP_PORT", 587))
        user = getattr(settings, "AXIOM_SMTP_USER", None)
        password = getattr(settings, "AXIOM_SMTP_PASSWORD", None)
        from_addr = getattr(settings, "AXIOM_SMTP_FROM", "axiom@dataops.ai")
        use_tls = getattr(settings, "AXIOM_SMTP_USE_TLS", True)

        log.info("notification.send_email", to=to, subject=subject, host=host, port=port)

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to
            if cc:
                msg["Cc"] = ", ".join(cc)

            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type, "utf-8"))

            recipients = [to] + (cc or [])

            if use_tls:
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(host, port, timeout=15)

            if user and password:
                server.login(user, password)

            server.sendmail(from_addr, recipients, msg.as_string())
            server.quit()

            log.info("notification.send_email.ok", to=to)
            return {"sent": True, "to": to}

        except smtplib.SMTPException as exc:
            log.error("notification.send_email.smtp_error", error=str(exc))
            return {"error": f"SMTP error: {str(exc)}"}
        except Exception as exc:
            log.error("notification.send_email.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 4. Preset: incident alert
    # ------------------------------------------------------------------

    async def notify_incident(
        self,
        incident_id: str,
        title: str,
        severity: str,
        pipeline_name: str | None = None,
        root_cause: str | None = None,
        channel: str = "slack",
    ) -> dict:
        """
        Convenience wrapper to notify about a new or escalated incident.
        Formats a structured alert from incident fields.
        """
        message_lines = [f"*Incident:* {title}"]
        if pipeline_name:
            message_lines.append(f"*Pipeline:* {pipeline_name}")
        if root_cause:
            message_lines.append(f"*Root Cause:* {root_cause}")
        message_lines.append(f"*Incident ID:* `{incident_id}`")
        message_lines.append("Respond via the AXIOM dashboard or agent.")

        return await self.send_alert(
            channel=channel,
            title=f"Incident Detected: {title}",
            message="\n".join(message_lines),
            severity=severity,
            metadata={"incident_id": incident_id, "pipeline": pipeline_name or "N/A"},
        )

    # ------------------------------------------------------------------
    # 5. Preset: stale source alert
    # ------------------------------------------------------------------

    async def notify_stale_sources(
        self,
        stale_list: list[dict],
        channel: str = "slack",
    ) -> dict:
        """
        Notify about stale data sources exceeding their expected refresh interval.

        Args:
            stale_list: list of dicts from Monitor.check_freshness()
            channel: "slack" | "email" | "both"
        """
        if not stale_list:
            return {"sent": False, "reason": "no stale sources to notify"}

        lines = []
        for s in stale_list[:10]:
            hours = s.get("hours_overdue", "?")
            name = s.get("source_name", "Unknown")
            lines.append(f"• *{name}* — {hours:.1f}h overdue")

        if len(stale_list) > 10:
            lines.append(f"… and {len(stale_list) - 10} more")

        message = f"*{len(stale_list)} data source(s) are overdue for refresh:*\n" + "\n".join(lines)
        severity = "high" if len(stale_list) >= 5 else "medium"

        return await self.send_alert(
            channel=channel,
            title="Stale Data Sources Detected",
            message=message,
            severity=severity,
            metadata={"stale_count": str(len(stale_list))},
        )

    # ------------------------------------------------------------------
    # 6. Preset: pipeline failure alert
    # ------------------------------------------------------------------

    async def notify_pipeline_failure(
        self,
        pipeline_name: str,
        run_id: str,
        error_message: str | None = None,
        quality_score: float | None = None,
        channel: str = "slack",
    ) -> dict:
        """
        Notify about a failed pipeline run.
        """
        lines = [
            f"*Pipeline:* {pipeline_name}",
            f"*Run ID:* `{run_id}`",
        ]
        if error_message:
            lines.append(f"*Error:* {error_message[:300]}")
        if quality_score is not None:
            lines.append(f"*Quality Score:* {quality_score}")

        return await self.send_alert(
            channel=channel,
            title=f"Pipeline Failed: {pipeline_name}",
            message="\n".join(lines),
            severity="high",
            metadata={"run_id": run_id},
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _format_email_body(
        self,
        title: str,
        message: str,
        severity: str,
        metadata: dict | None = None,
    ) -> str:
        """Generates a minimal HTML email body."""
        color = SEVERITY_COLOR.get(severity, "#888888")
        meta_rows = ""
        if metadata:
            rows = "".join(
                f"<tr><td style='padding:4px 8px;font-weight:600;'>{k}</td>"
                f"<td style='padding:4px 8px;'>{v}</td></tr>"
                for k, v in metadata.items()
            )
            meta_rows = f"""
            <table style='width:100%;border-collapse:collapse;margin-top:16px;font-size:14px;'>
              {rows}
            </table>"""

        # Convert newlines to <br>
        html_message = message.replace("\n", "<br>")

        return f"""
        <html><body style='font-family:sans-serif;max-width:600px;margin:auto;'>
          <div style='border-left:4px solid {color};padding:16px;background:#f9f8f5;'>
            <h2 style='margin:0 0 8px;color:#28251d;'>{title}</h2>
            <p style='color:#28251d;'>{html_message}</p>
            {meta_rows}
            <p style='margin-top:20px;font-size:12px;color:#7a7974;'>
              Sent by AXIOM — AI DataOps Engineer &nbsp;|&nbsp; {utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            </p>
          </div>
        </body></html>
        """