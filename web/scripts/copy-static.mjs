// No bundler. tsc emits ES modules; this copies the static shell alongside them.
import { cp, mkdir } from "node:fs/promises";
await mkdir("dist", { recursive: true });
for (const d of ["index.html", "login.html", "admin.html", "assets", "css"]) {
  await cp(`static/${d}`, `dist/${d}`, { recursive: true }).catch(() => {});
}
console.log("static copied to dist/");
