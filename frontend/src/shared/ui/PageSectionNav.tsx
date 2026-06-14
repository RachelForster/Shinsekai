import { ChevronRight } from "lucide-react";

import "./PageSectionNav.css";

export interface PageSectionNavItem {
  id: string;
  label: string;
}

interface PageSectionNavProps {
  ariaLabel: string;
  items: PageSectionNavItem[];
}

export function PageSectionNav({ ariaLabel, items }: PageSectionNavProps) {
  const scrollToSection = (id: string) => {
    const target = document.getElementById(id);
    if (!target) {
      return;
    }
    const header = target.closest(".page")?.querySelector(".page__header");
    const container = target.closest(".content-outlet");
    const headerRect = header instanceof HTMLElement ? header.getBoundingClientRect() : null;

    if (container instanceof HTMLElement) {
      const containerRect = container.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const headerOffset = headerRect ? Math.max(0, headerRect.bottom - containerRect.top) : 0;
      container.scrollTo({
        behavior: "smooth",
        top: container.scrollTop + targetRect.top - containerRect.top - headerOffset - 12,
      });
      return;
    }

    const targetRect = target.getBoundingClientRect();
    const headerOffset = headerRect ? Math.max(0, headerRect.bottom) : 0;
    window.scrollTo({
      behavior: "smooth",
      top: window.scrollY + targetRect.top - headerOffset - 12,
    });
  };

  return (
    <nav aria-label={ariaLabel} className="page-section-nav">
      {items.map((item) => (
        <button className="page-section-nav__item" key={item.id} onClick={() => scrollToSection(item.id)} type="button">
          <span>{item.label}</span>
          <ChevronRight aria-hidden className="page-section-nav__icon" />
        </button>
      ))}
    </nav>
  );
}
