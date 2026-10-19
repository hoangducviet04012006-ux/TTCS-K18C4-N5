"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

global.document = {
  readyState: "loading",
  addEventListener() {},
  getElementById() { return { hidden: false, className: "", textContent: "" }; }
};
global.window = { location: { href: "https://shop.example/trace.html?batch_code=LOT%2D001", origin: "https://shop.example" } };

const { getBatchCode } = require("../js/trace.js");

test("reads batch_code query parameter and decodes URL encoding", () => {
  assert.equal(getBatchCode("https://shop.example/trace.html?batch_code=LOT%2D001"), "LOT-001");
  assert.equal(getBatchCode("https://shop.example/trace.html?batch_code=LOT-B"), "LOT-B");
});

test("falls back to a path code when batch_code is absent", () => {
  assert.equal(getBatchCode("https://shop.example/trace/LOT-003/"), "LOT-003");
});

test("returns empty code for trace page without a batch code", () => {
  assert.equal(getBatchCode("https://shop.example/trace.html"), "");
});

test("handles multiple distinct batch codes without mixing them", () => {
  const codes = [
    "https://shop.example/trace.html?batch_code=LOT-A001",
    "https://shop.example/trace.html?batch_code=LOT-B002",
    "https://shop.example/trace.html?batch_code=LOT%2FC003"
  ];
  assert.deepEqual(codes.map(getBatchCode), ["LOT-A001", "LOT-B002", "LOT/C003"]);
});

test("query parameter takes priority over a path segment", () => {
  assert.equal(
    getBatchCode("https://shop.example/trace/OTHER?batch_code=LOT-QUERY"),
    "LOT-QUERY"
  );
});

test("public trace page loads an external deferred script, not inline JavaScript", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(path.join(__dirname, "..", "trace.html"), "utf8");
  assert.match(html, /<script src="js\/trace\.js\?v=\d+" defer><\/script>/);
  assert.doesNotMatch(html, /<script>[^]*?new RegExp/);
});

test("API configuration uses an empty same-origin default and no fake production host", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const config = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "config.json"), "utf8"));
  assert.equal(config.apiBase, "");
  assert.doesNotMatch(config.apiBase, /localhost|127\.0\.0\.1|example\.com/i);
});
