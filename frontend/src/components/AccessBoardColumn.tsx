import type { ReactNode } from "react";

export function AccessBoardColumn({ step, title, subtitle, children }: { step: number; title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="min-w-0 min-h-[310px] border border-[#2a2d30] bg-[#0e0f12]">
      <header className="border-b border-[#2a2d30] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="grid h-5 w-5 place-items-center rounded-full bg-[#34373b] font-mono text-xs text-[#f1f3f5]">{step}</span>
          <h3 className="text-xs font-semibold uppercase tracking-[.08em] text-[#f1f3f5]">{title}</h3>
        </div>
        <p className="mt-1 text-xs text-[#c2c6cc]">{subtitle}</p>
      </header>
      <div className="max-h-[360px] overflow-y-auto p-2">{children}</div>
    </section>
  );
}
