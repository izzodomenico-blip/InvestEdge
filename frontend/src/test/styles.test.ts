// @vitest-environment node
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import postcss, { type Root } from "postcss";
const tailwind = createRequire(import.meta.url)("@tailwindcss/postcss");
import { beforeAll, describe, expect, it } from "vitest";

let css: Root;
const frontend = fileURLToPath(new URL("../..", import.meta.url));

function value(selector: string, property: string): string | undefined {
  let result: string | undefined;
  css.walkRules((rule) => {
    if (!rule.selectors.includes(selector)) return;
    rule.walkDecls(property, (decl) => { result = decl.value; });
  });
  return result;
}
function token(name: string): string | undefined {
  let result: string | undefined;
  css.walkDecls(name, (decl) => { result = decl.value; });
  return result;
}

beforeAll(async () => {
  const entry = new URL("../index.css", import.meta.url);
  const result = await postcss([tailwind({ base: frontend })]).process(
    await readFile(entry, "utf8"), { from: fileURLToPath(entry) },
  );
  css = result.root;
}, 20_000);

describe("stili applicativi dopo la migrazione Tailwind", () => {
  it("non attiva l'alone che Tailwind v3 non generava", () => {
    expect(value(".bg-violet-400\\/8", "background-color")).toBeUndefined();
  });
  it("preserva il padding nativo dei campi data di Backtest", () => {
    expect(value('input[type="date"]::-webkit-datetime-edit', "padding-block")).toBe("revert");
    expect(value('input[type="date"]::-webkit-datetime-edit', "display")).toBe("revert");
    expect(value('input[type="date"]::-webkit-datetime-edit-fields-wrapper', "padding")).toBe("revert");
  });
  it("conserva palette v3 e token del tema InvestEdge", () => {
    expect(token("--color-cyan-300")).toBe("#67e8f9");
    expect(token("--color-slate-400")).toBe("#94a3b8");
    expect(token("--color-rose-400")).toBe("#fb7185");
    expect(value(".bg-ink-975", "background-color")).toBe("#04060B");
    expect(value(".eyebrow", "font-family")).toContain("JetBrains Mono");
    expect(value(".glass-card", "backdrop-filter")).toBe("blur(12px)");
    expect(value(".animate-fade-up", "animation")).toContain("fade-up");
  });
  it("preserva i valori v3 di blur e angoli delle classi usate", () => {
    expect(token("--blur-sm")).toBe("4px");
    expect(value(".backdrop-blur", "--tw-backdrop-blur")).toBe("blur(8px)");
    expect(value(".rounded", "border-radius")).toBe("0.25rem");
  });
  it("mantiene il reset dei font sotto le utility dei controlli", () => {
    const layers: string[] = [];
    css.walkDecls("font", (decl) => {
      if (decl.value !== "inherit") return;
      if (decl.parent?.type !== "rule" || decl.parent.selector.replace(/\s+/g, "") !== "button,input,select,textarea") return;
      let parent: postcss.Container | postcss.Document | undefined = decl.parent;
      while (parent) {
        if (parent instanceof postcss.AtRule && parent.name === "layer") layers.push(parent.params);
        parent = parent.parent;
      }
    });
    expect(layers).toContain("base");
    expect(value(".text-sm", "font-size")).toContain("--text-sm");
  });
  it("preserva spazi superiori e bordi delle righe ignorando elementi hidden", () => {
    expect(value(".space-y-2 > :not([hidden]) ~ :not([hidden])", "margin-top")).toContain("0.5rem");
    expect(value(".divide-y > :not([hidden]) ~ :not([hidden])", "border-top-width")).toContain("1px");
  });
  it("conserva outline accessibile e interpolazione sRGB dei gradienti", () => {
    expect(value(".outline-none", "outline")).toBe("2px solid transparent");
    expect(value(".bg-gradient-to-br", "--tw-gradient-position")).toBe("to bottom right in srgb");
    expect(value(".bg-gradient-to-br", "background-image")).toBe("linear-gradient(var(--tw-gradient-stops))");
    expect(value(".via-transparent", "--tw-gradient-via-stops")).toContain("--tw-gradient-position");
  });
});
