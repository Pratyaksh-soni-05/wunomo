"use client";

import { useState } from "react";

interface Slide {
  src: string;
  title: string;
  desc: string;
}

export function ScreenshotCarousel({ slides }: { slides: Slide[] }) {
  const [index, setIndex] = useState(0);

  const go = (i: number) => setIndex((i + slides.length) % slides.length);

  return (
    <div className="landing-carousel">
      <button className="landing-carousel-arrow prev" onClick={() => go(index - 1)} aria-label="Previous screenshot">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>
      <button className="landing-carousel-arrow next" onClick={() => go(index + 1)} aria-label="Next screenshot">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      <div className="landing-carousel-frame">
        <div className="landing-carousel-track" style={{ transform: `translateX(-${index * 100}%)` }}>
          {slides.map((s) => (
            <div className="landing-carousel-slide" key={s.src}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={s.src} alt={s.title} />
            </div>
          ))}
        </div>
        <div className="landing-carousel-caption">
          <span className="landing-carousel-caption-title">{slides[index].title}</span>
          <span className="landing-carousel-caption-desc">{slides[index].desc}</span>
        </div>
      </div>
      <div className="landing-carousel-dots">
        {slides.map((s, i) => (
          <button
            key={s.src}
            className={["landing-carousel-dot", i === index ? "active" : ""].join(" ")}
            onClick={() => go(i)}
            aria-label={`Go to slide ${i + 1}`}
          />
        ))}
      </div>
    </div>
  );
}
