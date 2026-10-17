# Instructions for AI coding agents

You are helping one member of a six-person hackathon team build a platelet exchange.

1. Read `CONTRACT.md` before writing any code. It defines every interface, data shape, endpoint, and file path. Follow it exactly.
2. Only edit files inside the folder your human owns (see `BRIEFS.md`). Never edit another team member's folder, `CONTRACT.md`, or `shared/*.json` unless your human owns them.
3. If the contract seems wrong or incomplete, stop and tell your human. Do not invent new endpoints, fields, or shapes, and do not work around the contract.
4. Use camelCase for variables and functions, PascalCase for classes, camelCase JSON keys, and American English spelling.
5. Ship a working stub that matches the contract first, then replace it with real logic. `main` must always run.
6. The code runs on an IBM LinuxONE instance: s390x, Ubuntu 24.04, Python 3.12, no Docker. The only third-party Python packages allowed are fastapi, uvicorn, psycopg2, and networkx. Everything else must use the Python standard library (no numpy, pandas, or scipy) unless your human says Neil has approved it. The dashboard uses plain HTML/CSS/JS, and libraries may load from a CDN in the browser.
7. Write small tests for your module using hand-made fixtures that match the contract's data shapes.
8. Keep pull requests small, and describe in one line what changed and which contract section it implements.
