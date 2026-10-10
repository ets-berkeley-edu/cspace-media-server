# serenade: Serena's Selenium tests

Browser tests of the admin app, written as the team writes them for BOA (bea), Damien (mrsbaylock) and Diablo
(xena): pytest, with a page object per screen in `pages/` and the tests in `tests/`.

They run against the local stack (`./serena up`), with the CollectionSpace simulator's synthetic accounts, in
headless Chrome. Never against QA or production: the tests sign in, and later ones will change settings and take
files down.

```
./serena up        # the stack, with the admin app at http://localhost:5373/admin/
./serena ui        # makes serenade/.venv on first use, then runs the tests
./serena ui -k sign_in --headed     # one test, with the browser showing
```

Needs Chrome on your computer. Selenium Manager (part of Selenium) finds the matching chromedriver. The packages
are pinned with hashes in `requirements.txt`; change `requirements.in` and run
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`.
