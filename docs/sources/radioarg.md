# Source: radioarg.net

Checked on 2026-11-08 at <https://radioarg.net/terminos-y-condiciones> and <https://radioarg.net/robots.txt>. Added at the maintainer's request.

- **robots.txt** disallows `/search` and URLs with a query string (except `?page=`). Station pages and the sitemap are allowed. The collector reads robots.txt first and obeys it.
- **Terms**, section 4: users must not reproduce or communicate to the public the portal's *Contents* unless the rights holder authorised it or the law allows it. Section 3.3: contents may be obtained by the usual means of the Internet, without risk of harm to the portal.
- **What is taken: facts only.** A station's name, country, town, the address of its stream, and its own website. Facts are not protected by copyright, and Argentina has no database right like the European Union's. No text, description, logo, rating, genre or other creative content is taken, and no link to radioarg.net is published.
- **Each stream is checked** to play before it is kept, so what is published is verified at the station's own server, not copied.
- **Politeness:** one page every two seconds, an identifiable User-Agent, the page's JavaScript never run, once a month.

Import: `pipeline/fetch_radioarg.py`, as the release asset `radioarg` of `moondust`.
