import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const navbar = await readFile(new URL("../src/components/Navbar.jsx", import.meta.url), "utf8");
const css = await readFile(new URL("../src/styles/index.css", import.meta.url), "utf8");

test("login route switch remains rendered on every unauthenticated auth page", () => {
  assert.match(navbar, /to="\/login"[\s\S]*?navbar-auth-login/);
  assert.doesNotMatch(navbar, /!loading && !onLoginPage && <Link to="\/login"/);
  assert.match(navbar, /aria-current=\{onLoginPage \? "page" : undefined\}/);
});

test("login route switch has explicit contrast in light and aurora themes", () => {
  assert.match(css, /\.navbar nav a\.navbar-auth-login[\s\S]*?color:\s*#34415c\s*!important/);
  assert.match(css, /:root\[data-theme="aurora"\] \.navbar nav a\.navbar-auth-login[\s\S]*?color:\s*#eeeaff\s*!important/);
});

test("login route switch has visible hover and keyboard focus states", () => {
  assert.match(css, /\.navbar nav a\.navbar-auth-login:hover[\s\S]*?outline:/);
  assert.match(css, /\.navbar nav a\.navbar-auth-login\.is-current/);
});
