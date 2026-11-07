# Source: Radio Browser

Checked on 2026-11-06 at <https://www.radio-browser.info/>.

- The home page states: "Data license: public domain".
- Its maintainer gives "all the rights I have" in the accumulated data to the public domain.
- The covered data is listed there: station names, tags, stream links, homepages, language, country, state.
- <https://api.radio-browser.info/> allows mirroring all the data, in free and non-free software.

Import: the daily export at <https://backups.radio-browser.info/>.

The export leaves out the checker's measures. They come from one request to the public API (`/json/stations`), the same data under the same dedication: only `codec`, `bitrate`, `hls` and `lastcheckok` are kept. Votes, clicks and other usage counts are never read.

A dated copy of the page is to be kept with the first release.

Rows that send to another directory (its redirects, pages or images) are excluded: they are not the station's own.
