"use client";

import { FormEvent, useState } from "react";
import { FORMSPREE_ENDPOINT, PRIMARY_CONTACT_EMAIL } from "@/lib/config";

type Status = "idle" | "sending" | "success" | "error";

// Real silent submit via Formspree's AJAX endpoint (fetch + Accept:
// application/json), per the approved decision - mailto was rejected
// because it fails silently for any visitor with no configured desktop
// mail client, which is exactly the visitor this form can't afford to
// lose. On error, this shows a real inline message with a mailto fallback
// rather than doing nothing - per the "must really send, or not exist,
// never submit into the void" requirement, a failed submit has to be
// visibly a failure, not a silent one either.
export function InterestForm() {
  const [status, setStatus] = useState<Status>("idle");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setStatus("sending");
    const form = e.currentTarget;
    const data = new FormData(form);

    try {
      const res = await fetch(FORMSPREE_ENDPOINT, {
        method: "POST",
        body: data,
        headers: { Accept: "application/json" },
      });
      if (res.ok) {
        setStatus("success");
        form.reset();
      } else {
        setStatus("error");
      }
    } catch {
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div className="card" style={{ padding: 24, textAlign: "center" }}>
        <p style={{ margin: 0 }}>Thanks — we got it, and we&apos;ll be in touch shortly.</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="landing-interest-form">
      <div className="input-group">
        <label className="input-label" htmlFor="if-name">Name</label>
        <input id="if-name" name="name" type="text" className="input" required disabled={status === "sending"} />
      </div>
      <div className="input-group">
        <label className="input-label" htmlFor="if-email">Email</label>
        <input id="if-email" name="email" type="email" className="input" required disabled={status === "sending"} />
      </div>
      <div className="input-group">
        <label className="input-label" htmlFor="if-company">Company (optional)</label>
        <input id="if-company" name="company" type="text" className="input" disabled={status === "sending"} />
      </div>
      <div className="input-group">
        <label className="input-label" htmlFor="if-message">What are you looking to solve?</label>
        <textarea id="if-message" name="message" className="input" rows={4} disabled={status === "sending"} />
      </div>

      {status === "error" && (
        <p className="input-hint text-danger" style={{ marginBottom: 4 }}>
          Something went wrong sending that — please email us directly at{" "}
          <a href={`mailto:${PRIMARY_CONTACT_EMAIL}`}>{PRIMARY_CONTACT_EMAIL}</a> instead.
        </p>
      )}

      <button type="submit" className="btn btn-primary" disabled={status === "sending"}>
        {status === "sending" ? "Sending…" : "Send"}
      </button>
    </form>
  );
}
