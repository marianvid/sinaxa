"""Static checks on the page.

These exist because of two real bugs: `SEL` was used but never declared, and
`const ROLES` was cut out with the dialogs it happened to sit between. Both
killed a function at runtime; neither is a syntax error, so `node --check`
saw nothing wrong.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "ui", "sinaxa.html"), encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "ui", "sinaxa.css"), encoding="utf-8").read()
JS_RAW = re.search(r"<script>(.*)</script>", HTML, re.S).group(1)


def _regex_here(src, i):
    """True if the slash at i opens a regex literal rather than a division."""
    j = i - 1
    while j >= 0 and src[j] in " \t\n":
        j -= 1
    return j < 0 or src[j] in "(,=:[!&|?{};+*%<>~^"


def code_only(src):
    """Strip comments and string bodies so the scanners read code, not prose.

    Template literals keep what is inside ${...} — that part is real code.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//":
            i = src.find("\n", i)
            if i < 0:
                break
        elif two == "/*":
            i = src.find("*/", i) + 2
        elif src[i] in "'\"":
            quote, i = src[i], i + 1
            while i < n and src[i] != quote:
                i += 2 if src[i] == "\\" else 1
            i += 1
        elif src[i] == "/" and _regex_here(src, i):
            i += 1                       # a regex literal: /.../flags
            while i < n and src[i] != "/":
                if src[i] == "[":        # a class may hold an unescaped /
                    while i < n and src[i] != "]":
                        i += 2 if src[i] == "\\" else 1
                i += 2 if src[i] == "\\" else 1
            i += 1
        elif src[i] == "`":
            i += 1
            while i < n and src[i] != "`":
                if src[i:i + 2] == "${":
                    depth, i = 1, i + 2
                    while i < n and depth:
                        if src[i] == "{":
                            depth += 1
                        elif src[i] == "}":
                            depth -= 1
                        if depth:
                            out.append(src[i])
                        i += 1
                    out.append(" ")
                else:
                    i += 2 if src[i] == "\\" else 1
            i += 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


JS = code_only(JS_RAW)

BUILTINS = {
    "JSON", "Object", "Set", "Map", "Date", "String", "Number", "Math", "Array",
    "Promise", "RegExp", "Error", "Boolean", "URLSearchParams", "Event", "FileReader",
}


class Identifiers(unittest.TestCase):
    def declared(self):
        return set(re.findall(r"(?:let|const|var|function)\s+(\w+)", JS)) | BUILTINS

    def test_every_capitalised_name_is_declared(self):
        used = set(re.findall(r"\b([A-Z][A-Za-z_]*)\s*(?=[.(\[])", JS))
        missing = sorted(u for u in used if u not in self.declared())
        self.assertEqual(missing, [], "used but never declared: %s" % missing)

    def parameters(self):
        """Names bound by a parameter list — a callback passed in is defined."""
        names = set()
        for params in re.findall(r"function\s*\w*\s*\(([^)]*)\)", JS) \
                    + re.findall(r"\(([^)]*)\)\s*=>", JS):
            names |= set(re.findall(r"\b([a-z]\w*)", params))
        names |= set(re.findall(r"(\w+)\s*=>", JS))
        return names

    def test_every_function_called_is_defined(self):
        defined = set(re.findall(r"function\s+(\w+)", JS)) \
                | set(re.findall(r"(?:const|let)\s+(\w+)\s*=\s*(?:\(|async|\w+\s*=>)", JS)) \
                | self.parameters()
        called = set(re.findall(r"(?<![.\w])([a-z]\w+)\s*\(", JS))
        known = defined | {
            "if", "for", "while", "switch", "catch", "return", "typeof", "await",
            "fetch", "parseInt", "parseFloat", "alert", "prompt", "confirm",
            "setTimeout", "setInterval", "clearTimeout", "requestAnimationFrame",
            "isNaN", "of", "in", "new", "var",
        }
        missing = sorted(c for c in called if c not in known)
        self.assertEqual(missing, [], "called but never defined: %s" % missing)


class Markup(unittest.TestCase):
    def test_every_element_looked_up_by_id_exists(self):
        wanted = set(re.findall(r"getElementById\(['\"](\w[\w-]*)['\"]\)", JS))
        present = set(re.findall(r'id="([\w-]+)"', HTML))
        missing = sorted(wanted - present)
        self.assertEqual(missing, [], "no such id in the markup: %s" % missing)

    def test_the_stylesheet_is_linked_and_no_styles_are_inline(self):
        self.assertIn('href="/sinaxa.css"', HTML)
        self.assertNotIn("<style>", HTML)

    def test_the_old_name_is_gone(self):
        for dead in ("kenbet", "foundry"):
            self.assertNotIn(dead, HTML.lower())
            self.assertNotIn(dead, CSS.lower())


class Saving(unittest.TestCase):
    """A Save that saves nothing teaches you to press it without reading.

    The behaviour itself was checked in a browser: every form opens with Save
    disabled, comes alive on a real change, and dies again when the change is
    undone. What can be checked here is that the wiring is still in place.
    """

    def test_every_edit_form_tracks_whether_anything_changed(self):
        """One watch() per form that saves: members, roles, projects,
        sessions, rooms -- and one per seat row in Manage team."""
        self.assertGreaterEqual(JS.count("watch("), 6)

    def test_each_seat_row_has_its_own_guard(self):
        self.assertIn("scrim.querySelectorAll('[data-seat]')", JS_RAW)
        self.assertIn("watch(row, save,", JS)

    def test_a_destructive_confirmation_is_not_gated_on_a_change(self):
        """Removing without ticking the box is a legitimate answer, so those
        dialogs keep a live button: modal(..., 'Remove', true)."""
        self.assertEqual(JS_RAW.count("'Remove', true)"), 3)

    def test_the_prompt_box_shows_the_prompt_in_force(self):
        self.assertIn("prompt_effective", HTML)
        self.assertNotIn("Use default", HTML)
        self.assertIn("Reset to default", HTML)


class Theme(unittest.TestCase):
    """A colour defined only in the dark block leaves the light theme broken."""

    def block(self, selector):
        m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", CSS, re.S)
        return set(re.findall(r"(--[\w-]+)\s*:", m.group(1))) if m else set()

    def test_both_themes_define_the_same_variables(self):
        dark = self.block(':root,\n:root[data-theme="dark"]')
        light = self.block(':root[data-theme="light"]')
        self.assertTrue(dark, "no dark palette found")
        self.assertTrue(light, "no light palette found")
        only_dark = sorted(dark - light - {"--radius", "--shadow"})
        self.assertEqual(only_dark, [],
                         "missing from the light theme: %s" % only_dark)

    def test_no_raw_colour_outside_the_palette(self):
        body = CSS[CSS.index("*{box-sizing"):]
        raw = re.findall(r":\s*(#[0-9a-fA-F]{3,8})\b", body)
        self.assertEqual(raw, [], "hardcoded colours outside :root: %s" % raw)


if __name__ == "__main__":
    unittest.main()
