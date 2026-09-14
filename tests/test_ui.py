"""Static checks for the four isolated UI pages."""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "ui")
PAGES = ("projects", "members", "seats", "settings")


def read(name, suffix):
    with open(os.path.join(UI, name + suffix), encoding="utf-8") as handle:
        return handle.read()


def _regex_here(src, i):
    j = i - 1
    while j >= 0 and src[j] in " \t\n":
        j -= 1
    return j < 0 or src[j] in "(,=:[!&|?{};+*%<>~^"


def code_only(src):
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
            i += 1
            while i < n and src[i] != "/":
                if src[i] == "[":
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


BUILTINS = {"JSON", "Object", "Set", "Map", "Date", "String", "Number",
            "Math", "Array", "Promise", "RegExp", "Error", "Boolean",
            "URLSearchParams", "Event", "FileReader"}


class Structure(unittest.TestCase):
    def test_every_section_has_its_own_three_files(self):
        for page in PAGES:
            for suffix in (".html", ".css", ".js"):
                self.assertTrue(os.path.isfile(os.path.join(UI, page + suffix)))

    def test_each_page_links_only_its_own_assets(self):
        for page in PAGES:
            html = read(page, ".html")
            self.assertIn('href="/%s.css"' % page, html)
            self.assertIn('src="/%s.js"' % page, html)
            self.assertNotIn("<style>", html)
            self.assertNotRegex(html, r"<script>(.|\n)*</script>")

    def test_all_navigation_targets_exist_on_every_page(self):
        for page in PAGES:
            html = read(page, ".html")
            for target in PAGES:
                self.assertIn('href="/%s.html"' % target, html)

    def test_every_looked_up_id_exists_on_its_page(self):
        for page in PAGES:
            html, js = read(page, ".html"), read(page, ".js")
            wanted = set(re.findall(r"getElementById\(['\"](\w[\w-]*)['\"]\)", js))
            present = set(re.findall(r'id="([\w-]+)"', html))
            dynamic = set(re.findall(r'id=\\?"([\w-]+)\\?"', js))
            self.assertEqual(sorted(wanted - present - dynamic), [], page)

    def test_old_monolith_is_not_served(self):
        with open(os.path.join(ROOT, "src", "server.py"), encoding="utf-8") as handle:
            server = handle.read()
        self.assertNotIn("sinaxa.html", server)
        self.assertNotIn("sinaxa.css", server)


class Javascript(unittest.TestCase):
    def test_each_script_parses(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        for page in PAGES:
            result = subprocess.run([node, "--check", os.path.join(UI, page + ".js")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_capitalised_names_are_declared_per_script(self):
        for page in PAGES:
            js = code_only(read(page, ".js"))
            declared = set(re.findall(r"(?:let|const|var|function)\s+(\w+)", js)) | BUILTINS
            used = set(re.findall(r"\b([A-Z][A-Za-z_]*)\s*(?=[.(\[])", js))
            self.assertEqual(sorted(used - declared), [], page)


class Theme(unittest.TestCase):
    def block(self, css, selector):
        match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
        return set(re.findall(r"(--[\w-]+)\s*:", match.group(1))) if match else set()

    def test_each_page_has_a_complete_palette(self):
        for page in PAGES:
            css = read(page, ".css")
            dark = self.block(css, ':root,\n:root[data-theme="dark"]')
            light = self.block(css, ':root[data-theme="light"]')
            self.assertTrue(dark, page)
            self.assertEqual(sorted(dark - light - {"--radius", "--shadow"}), [], page)


if __name__ == "__main__":
    unittest.main()
