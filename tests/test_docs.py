"""The README and every document in docs/ and .github/: each relative link and image points at a file
that is there (and at a #heading or #L line that is there), every picture has alt text and is used,
and none is heavy. Markdown links and HTML <a>/<img> tags both count."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md")), *sorted((ROOT / ".github").glob("*.md"))]
IMAGES = ROOT / "docs" / "images"
# links GitHub resolves against the repository page, not against a file
WEB_PATHS = ("../../releases/latest",)
WIKI = ROOT / "docs" / "wiki"
# the GitHub Wiki's menu links pages by name, without .md; these names are not files in docs/wiki
SIDEBAR_NAMES = {"Home": "README.md", "How-It-Was-Built": "../HOW_IT_WAS_BUILT.md",
                 "How-It-Was-Tuned": "../HOW_IT_WAS_TUNED.md"}
MAX_IMAGE_BYTES = 500_000

LINK = re.compile(r"(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")
TAG = re.compile(r"<(img|a)\b([^>]*)>", re.I)
ATTR = re.compile(r"""\b(src|href|alt)\s*=\s*("([^"]*)"|'([^']*)')""", re.I)
LINES = re.compile(r"L(\d+)(?:-L(\d+))?")


def prose(text: str) -> str:
    """The text without fenced code blocks and inline code, where brackets and tags are not links."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    return re.sub(r"`[^`\n]*`", "", text)


def links_in(text: str) -> list:
    """(is_image, text, target) for every link and image: Markdown ones, the image inside
    [![...](...)](...), and HTML <img src alt> and <a href>."""
    found, text = [], prose(text)
    for m in LINK.finditer(text):
        found.append((m.group(1) == "!", m.group(2), m.group(3)))
        found += [(True, i.group(2), i.group(3)) for i in LINK.finditer(m.group(2)) if i.group(1) == "!"]
    for m in TAG.finditer(text):
        attrs = {a.group(1).lower(): a.group(3) if a.group(3) is not None else a.group(4) for a in ATTR.finditer(m.group(2))}
        if m.group(1).lower() == "img" and "src" in attrs:
            found.append((True, attrs.get("alt", ""), attrs["src"]))
        elif m.group(1).lower() == "a" and "href" in attrs:
            found.append((False, "", attrs["href"]))
    return found


def links(path: Path) -> list:
    return links_in(path.read_text(encoding="utf-8"))


def external(target: str) -> bool:
    return bool(re.match(r"[a-z][a-z0-9+.-]*:", target, re.I)) or target in WEB_PATHS


def anchors(path: Path) -> set:
    """GitHub's heading ids: lower case, punctuation dropped, spaces to hyphens, repeats numbered."""
    seen, out = {}, set()
    for line in prose(path.read_text(encoding="utf-8")).splitlines():
        m = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))       # a link keeps only its text
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        out.add(slug if n == 0 else f"{slug}-{n}")
    return out


class DocLinkTests(unittest.TestCase):
    def test_the_docs_are_there(self):
        for name in ("README.md", "docs/DEVELOPMENT.md", "docs/CALIBRATION.md", "docs/HOW_IT_WAS_TUNED.md"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_every_relative_link_and_image_resolves(self):
        checked = 0
        for doc in DOCS:
            for is_image, _text, target in links(doc):
                if external(target):
                    continue                                     # https:, mailto: and GitHub's own pages
                with self.subTest(doc=str(doc.relative_to(ROOT)), target=target):
                    if doc.name == "_Sidebar.md":
                        target = SIDEBAR_NAMES.get(target, target + ".md")
                    file_part, _, anchor = target.partition("#")
                    dest = (doc.parent / file_part).resolve() if file_part else doc
                    self.assertTrue(dest.exists(), f"{doc.name} links to {target}, which is not there")
                    self.assertTrue(dest.is_relative_to(ROOT), f"{doc.name}: {target} leaves the repository")
                    if anchor and dest.suffix == ".md":
                        self.assertIn(anchor, anchors(dest), f"{doc.name}: no heading #{anchor} in {dest.name}")
                    elif anchor:
                        m = LINES.fullmatch(anchor)
                        self.assertIsNotNone(m, f"{doc.name}: #{anchor} into {dest.name} is not a line anchor")
                        count = len(dest.read_text(encoding="utf-8").splitlines())
                        self.assertLessEqual(int(m.group(2) or m.group(1)), count, f"{target}: past the end")
                    if is_image:
                        self.assertEqual(dest.parent, IMAGES, f"{target}: images live in docs/images")
                    checked += 1
        self.assertGreater(checked, 10)

    def test_every_image_has_alt_text_is_used_and_is_light(self):
        used = set()
        for doc in DOCS:
            for is_image, alt, target in links(doc):
                if not is_image:
                    continue
                with self.subTest(doc=str(doc.relative_to(ROOT)), image=target):
                    if external(target):
                        self.assertTrue(alt.strip(), "a badge says what it is too")
                    else:
                        self.assertGreater(len(alt.strip()), 10, "say what the image shows")
                        used.add((doc.parent / target).resolve())
        for image in IMAGES.iterdir():
            with self.subTest(image=image.name):
                self.assertEqual(image.suffix, ".png")
                self.assertIn(image.resolve(), used, "an image no document shows")
                self.assertLessEqual(image.stat().st_size, MAX_IMAGE_BYTES)

    def test_the_readme_shows_the_tuning_chart(self):
        readme = links(ROOT / "README.md")
        self.assertIn((True, "docs/images/improvement.png"), {(i, t) for i, _a, t in readme})

    def test_the_wiki_and_github_files_are_covered(self):
        covered = {str(d.relative_to(ROOT)).replace("\\", "/") for d in DOCS}
        for name in ("docs/wiki/README.md", "docs/wiki/Features.md", "docs/wiki/Games.md", "docs/wiki/Effects.md",
                     "docs/wiki/Trackmania.md", ".github/CONTRIBUTING.md"):
            if (ROOT / name).exists():
                self.assertIn(name, covered)

    def test_the_wiki_index_sidebar_and_reading_order_agree(self):
        """Every guide page is in the index and in the sidebar once, in the same order; each page says where
        it sits and links to the next one in that order."""
        pages = sorted(p.stem for p in WIKI.glob("*.md") if not p.name.startswith("_") and p.name != "README.md")
        index = list(dict.fromkeys(t[:-3] for _i, _a, t in links(WIKI / "README.md") if re.fullmatch(r"[\w.-]+\.md", t)))
        sidebar = [t for _i, _a, t in links(WIKI / "_Sidebar.md") if t not in SIDEBAR_NAMES]
        self.assertEqual(sorted(index), pages, "the index lists every page, once")
        self.assertEqual(sidebar, index, "the sidebar has the index's pages in the index's order")
        for page, nxt in zip(index, index[1:] + [None]):
            with self.subTest(page=page):
                text = (WIKI / f"{page}.md").read_text(encoding="utf-8")
                self.assertRegex(text, r"\A# .+\n\n\[OpenShaker guide\]\(README\.md\) › .+\n", "title and breadcrumb")
                m = re.search(r"^\*\*Next:\*\* (.*)$", text, re.M)
                self.assertIsNotNone(m, "a Next link at the end")
                self.assertIn(f"({nxt}.md)" if nxt else "(README.md)", m.group(1))

    def test_the_link_finder_itself(self):
        self.assertIn("known-gaps", anchors(ROOT / "docs" / "CALIBRATION.md"))
        self.assertIn("disclaimer-and-license", anchors(ROOT / "README.md"))
        text = ("[![a b](x.png)](y.md) `[code](a.md)` [c](z.md#h)\n```\n[fenced](b.md)\n```\n"
                '<p align="center"><img src="logo.png" alt="The logo" width="128"></p> <a href="w.md">w</a>\n')
        self.assertEqual(links_in(text), [(False, "![a b](x.png)", "y.md"), (True, "a b", "x.png"),
                                          (False, "c", "z.md#h"), (True, "The logo", "logo.png"), (False, "", "w.md")])
        self.assertEqual(LINES.fullmatch("L18-L93").groups(), ("18", "93"))
        self.assertTrue(external("https://img.shields.io/x") and external("../../releases/latest"))


if __name__ == "__main__":
    unittest.main()
