# Third-party notices

QuickMorph ships these files unmodified so math and diagrams render **offline**:

| Component | Version | Files | License |
| --- | --- | --- | --- |
| [KaTeX](https://github.com/KaTeX/KaTeX) | 0.19.0 | `quickmorph/vendor/katex/` (JS, CSS, woff2 fonts) | MIT - see `quickmorph/vendor/katex/LICENSE` |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 12.2.0 | `quickmorph/vendor/mermaid/mermaid.min.js` | MIT - see `quickmorph/vendor/mermaid/LICENSE` |

The Mermaid bundle includes further open-source libraries (d3, dagre, DOMPurify, cytoscape, khroma,
lodash-es, marked, dayjs, roughjs, stylis and others) under their own permissive licenses (MIT, ISC,
BSD, Apache-2.0); see Mermaid's `package.json` / repository for the full list.

Python libraries are **not** bundled - the installer downloads them from PyPI (see `requirements.txt`):
markdown-it-py, mdit-py-plugins, linkify-it-py (MIT), Pygments (BSD-2-Clause), mammoth (BSD-2-Clause),
docutils (public domain / BSD-2-Clause).
