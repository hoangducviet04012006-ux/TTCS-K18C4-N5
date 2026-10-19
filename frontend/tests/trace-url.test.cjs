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
  assert.equal(getBatchCode("https://shop.example/trace.html"), "trace.html");
});
