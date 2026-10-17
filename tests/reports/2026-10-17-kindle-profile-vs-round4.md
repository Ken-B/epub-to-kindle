# Converter quality report: real-local-generated (2026-10-17)

418 results across azw3, mobi. Gap categories and their kinds are defined in `tests/harness/schema.md`; a book can carry several categories.

## Before vs after

Baseline: `tests/corpus/round4-results` (result files of the original writer). Books are paired by sha256 and format; categories are recomputed with the current taxonomy on both sides. A lower count is better in every category row.

### AZW3: 209 paired books, 209 regressed

| metric | before | after |
|---|---|---|
| books with an output file | 209/209 | 209/209 |
| gate pass (all three parsers) | 209/209 (100.0%) | 209/209 (100.0%) |
| mean style score, se+pg books | 1.000 (n=200) | 0.730 (n=200) |
| mean device score, se+pg books | 0.888 (n=200) | 0.995 (n=200) |
| layout hygiene, pooled (empty blocks / trailing breaks / whitespace runs / nbsp indents) | 167 / 1815 / 648729 / 16 | 21 / 0 / 0 / 9 |
| internal links resolved (pooled) | 29021/29021 (100.0%) | 29021/29021 (100.0%) |
| image refs correct (pooled) | 3570/3570 (100.0%) | 3568/3570 (99.9%) |
| images present by hash (pooled) | 3085/3085 (100.0%) | 3085/3085 (100.0%) |
| spine items with matching text (pooled) | 4366/4367 (100.0%) | 4366/4367 (100.0%) |
| TOC entries matched (pooled) | 8928/8928 (100.0%) | 8928/8928 (100.0%) |

| category | books before | books after | delta |
|---|---|---|---|
| `images-misreferenced` | 0 | 1 | +1 |
| `style-lost` | 0 | 10 | +10 |
| `device-style-lost` | 61 | 0 | -61 |
| `layout-hygiene` | 209 | 17 | -192 |
| `calibre-header-diff` | 209 | 209 | 0 |
| `input-repair` | 1 | 1 | 0 |

#### AZW3 regressions (209)

Reason counts (a book can have several): style score 209; new category 11; image refs correct 1; device score 1

| book | corpus category | why |
|---|---|---|
| `real/gutenberg/pg17016` | pg | style score 1.00 -> 0.66 |
| `real/…e-roosevelt_a-book-lovers-holidays-in-the-open` | se | style score 1.00 -> 0.81 |
| `real/gutenberg/pg44342` | pg | style score 1.00 -> 0.74 |
| `real/gutenberg/pg29047` | pg | style score 1.00 -> 0.63 |
| `real/gutenberg/pg36902` | pg | style score 1.00 -> 0.69 |
| `real/…ks/e-nesbit_beautiful-stories-from-shakespeare` | se | style score 1.00 -> 0.76 |
| `generated/gen-wrong-media-types` | generated | style score 1.00 -> 0.10; new categories: style-lost |
| `real/standard-ebooks/ring-lardner_fred-gross-stories` | se | style score 1.00 -> 0.84 |
| `real/…arlotte-m-yonge_the-clever-woman-of-the-family` | se | style score 1.00 -> 0.78 |
| `real/gutenberg/pg72234` | pg | style score 1.00 -> 0.61 |
| `real/gutenberg/pg66997` | pg | style score 1.00 -> 0.85 |
| `real/…ard-ebooks/george-macdonald_within-and-without` | se | style score 1.00 -> 0.90 |
| `real/…rd-ebooks/mary-p-hamlin_george-arliss_hamilton` | se | style score 1.00 -> 0.86 |
| `real/gutenberg/pg30274` | pg | style score 1.00 -> 0.61 |
| `real/gutenberg/pg8932` | pg | style score 1.00 -> 0.66 |
| `real/gutenberg/pg15228` | pg | style score 1.00 -> 0.67 |
| `real/gutenberg/pg30963` | pg | style score 1.00 -> 0.61 |
| `real/…ndard-ebooks/noel-loomis_short-science-fiction` | se | style score 1.00 -> 0.75 |
| `real/standard-ebooks/harry-harrison_short-fiction` | se | style score 1.00 -> 0.75 |
| `real/gutenberg/pg50820` | pg | style score 1.00 -> 0.78 |
| `real/gutenberg/pg48323` | pg | style score 1.00 -> 0.64 |
| `real/gutenberg/pg7199` | pg | style score 1.00 -> 0.78 |
| `real/standard-ebooks/h-c-mcneile_the-third-round` | se | style score 1.00 -> 0.77 |
| `real/gutenberg/pg60297` | pg | style score 1.00 -> 0.81 |
| `real/gutenberg/pg67331` | pg | style score 1.00 -> 0.66 |
| `real/gutenberg/pg59227` | pg | style score 1.00 -> 0.74 |
| `real/standard-ebooks/dornford-yates_blind-corner` | se | style score 1.00 -> 0.75 |
| `real/gutenberg/pg7237` | pg | style score 1.00 -> 0.75 |
| `real/gutenberg/pg19246` | pg | style score 1.00 -> 0.83 |
| `real/gutenberg/pg71277` | pg | style score 1.00 -> 0.68 |
| `real/gutenberg/pg62947` | pg | style score 1.00 -> 0.58 |
| `real/gutenberg/pg5578` | pg | style score 1.00 -> 0.67 |
| `real/…dard-ebooks/kahlil-gibran_jesus-the-son-of-man` | se | style score 1.00 -> 0.77 |
| `real/…d-ebooks/p-g-wodehouse_the-adventures-of-sally` | se | style score 1.00 -> 0.79 |
| `real/gutenberg/pg27367` | pg | style score 1.00 -> 0.58 |
| `real/gutenberg/pg16578` | pg | style score 1.00 -> 0.68 |
| `real/gutenberg/pg34377` | pg | style score 1.00 -> 0.64 |
| `real/gutenberg/pg29559` | pg | style score 1.00 -> 0.64 |
| `real/standard-ebooks/h-g-wells_the-wheels-of-chance` | se | style score 1.00 -> 0.80 |
| `real/…d-ebooks/edgar-rice-burroughs_pirates-of-venus` | se | style score 1.00 -> 0.76 |
| `real/gutenberg/pg31085` | pg | style score 1.00 -> 0.63 |
| `real/…ard-ebooks/robert-hugh-benson_the-necromancers` | se | style score 1.00 -> 0.78 |
| `real/…dard-ebooks/anthony-trollope_dr-wortles-school` | se | style score 1.00 -> 0.78 |
| `real/gutenberg/pg43593` | pg | style score 1.00 -> 0.68 |
| `real/…d-ebooks/catherine-louisa-pirkis_short-fiction` | se | style score 1.00 -> 0.79 |
| `real/…andard-ebooks/norman-angell_the-great-illusion` | se | style score 1.00 -> 0.80 |
| `real/…ard-ebooks/rudolph-fisher_the-walls-of-jericho` | se | style score 1.00 -> 0.76 |
| `real/gutenberg/pg71842` | pg | style score 1.00 -> 0.69 |
| `real/…leridge_robert-southey_the-fall-of-robespierre` | se | style score 1.00 -> 0.90 |
| `real/gutenberg/pg2175` | pg | style score 1.00 -> 0.78 |
| `real/gutenberg/pg36578` | pg | style score 1.00 -> 0.73 |
| `real/standard-ebooks/noel-coward_hay-fever` | se | style score 1.00 -> 0.85 |
| `real/gutenberg/pg72476` | pg | style score 1.00 -> 0.85 |
| `real/gutenberg/pg461` | pg | style score 1.00 -> 0.74 |
| `real/gutenberg/pg16866` | pg | style score 1.00 -> 0.66 |
| `real/…d-ebooks/david-hume_a-treatise-of-human-nature` | se | style score 1.00 -> 0.80 |
| `real/gutenberg/pg52657` | pg | style score 1.00 -> 0.69 |
| `real/…dard-ebooks/a-e-w-mason_the-house-of-the-arrow` | se | style score 1.00 -> 0.76 |
| `real/gutenberg/pg70584` | pg | style score 1.00 -> 0.65 |
| `real/gutenberg/pg58344` | pg | style score 1.00 -> 0.29; new categories: style-lost |
| ... | | 149 more in the JSON report (`before_after`) |

### MOBI: 209 paired books, 0 regressed

| metric | before | after |
|---|---|---|
| books with an output file | 209/209 | 209/209 |
| gate pass (all three parsers) | 209/209 (100.0%) | 209/209 (100.0%) |
| mean style score, se+pg books | 0.748 (n=200) | 0.748 (n=200) |
| mean device score, se+pg books | n/a | n/a |
| layout hygiene, pooled (empty blocks / trailing breaks / whitespace runs / nbsp indents) | 241 / 1436 / 614888 / 16 | 241 / 1436 / 614888 / 16 |
| internal links resolved (pooled) | 28987/28991 (100.0%) | 28987/28991 (100.0%) |
| image refs correct (pooled) | 3423/3531 (96.9%) | 3423/3531 (96.9%) |
| images present by hash (pooled) | 3001/3085 (97.3%) | 3001/3085 (97.3%) |
| spine items with matching text (pooled) | 4353/4367 (99.7%) | 4353/4367 (99.7%) |
| TOC entries matched (pooled) | 8928/8928 (100.0%) | 8928/8928 (100.0%) |

| category | books before | books after | delta |
|---|---|---|---|
| `text-loss` | 1 | 1 | 0 |
| `images-unextractable` | 1 | 1 | 0 |
| `links-unresolved` | 1 | 1 | 0 |
| `style-lost` | 29 | 29 | 0 |
| `layout-hygiene` | 209 | 209 | 0 |
| `calibre-header-diff` | 209 | 209 | 0 |
| `input-repair` | 1 | 1 | 0 |

#### MOBI regressions (0)

None.

## Format: azw3

### 1. Summary

209 books were run for AZW3; 209 (100%) produced an output file. 209 of 209 (100%) converted books pass all three parser gates (mobitool, KindleUnpack, Calibre reader). 11 books carry at least one actionable gap (a book can carry several kinds): 10 have unported Calibre transform gaps (91%), 1 have input repair gaps (9%), 1 have writer bug gaps (9%); 12 category findings in total. Verdict: unported Calibre transform gaps affect the most books (91%), so the next effort should port the missing Calibre transforms, starting with `style-lost`. 198 of 209 books have no actionable gap and were fully evaluated. Mean style score on se+pg books: preservation 0.730 (n=200), Kindle device model 0.995 (n=200). Layout hygiene, pooled over 209 books (empty blocks / trailing breaks / whitespace runs / nbsp indents): output 21 / 0 / 0 / 9, input 167 / 1815 / 648461 / 16; 17 books have at least one in the output. Not counted in `layout-hygiene` (styled empty blocks / double trailing breaks / ambiguous nbsp indents): output 68 / 54 / 426, input 72 / 54 / 467. Not counted above (category findings): 226 informational.

### 2. Top gap categories by affected books

| # | category | books | % of books | description | kind |
|---|---|---|---|---|---|
| 1 | `style-lost` | 10 | 5% | Style score below 0.5, or the input has CSS rules and the output none | unported Calibre transform |
| 2 | `images-misreferenced` | 1 | 0% | Image references in the text point at the wrong image or at none | writer bug |
| 3 | `input-repair` | 1 | 0% | App failed or lost text on a malformed input Calibre converted anyway | input repair |

Informational, acceptable, harness and out-of-scope categories are not ranked here (`calibre-header-diff`, `images-resized`, `images-unextractable`, `spine-non-xhtml`, `layout-hygiene`, `app-clean-error`, `harness-error`, `fixed-layout-unsupported`), and nothing on a fixed-layout book is; they appear in the per-category breakdown and the per-book table. `text-loss` counts as `input repair` on books whose verdict is error/warning, otherwise as `writer bug`.

### 3. Books most needing a manual look in Kindle Previewer

Ranked: gate failure, then misreferenced images, then lowest style score, then text-loss, then unresolved links. Only books with an output file are eligible; fixed-layout books are not.

| # | book | corpus category | why |
|---|---|---|---|
| 1 | `real/gutenberg/pg63372` | pg | image refs 126/128 correct (0 wrong, 2 missing) |
| 2 | `generated/gen-footnotes-ok` | generated | style score 0.04 |
| 3 | `generated/gen-duplicate-ids` | generated | style score 0.07 |
| 4 | `generated/gen-latin1-declared` | generated | style score 0.08 |
| 5 | `generated/gen-latin1-undeclared` | generated | style score 0.09; text 2/3 spine items match |

### 4. Gap categories by corpus category

| corpus category | books | `images-misreferenced` | `style-lost` | `layout-hygiene` | `calibre-header-diff` | `input-repair` |
|---|---|---|---|---|---|---|
| generated | 8 |  | 8 |  | 8 | 1 |
| local | 1 |  |  |  | 1 |  |
| pg | 100 | 1 | 2 | 17 | 100 |  |
| se | 100 |  |  |  | 100 |  |
| **total** | 209 | 1 | 10 | 17 | 209 | 1 |

### 5. All books

| id | category | verdict | app ok | calibre ok | gate pass | text match/spine | images matched/referenced | image refs ok/total | toc matched/input | links resolved/total | style | device style | hygiene out (e/b/ws/nb) | css rules out/in | categories |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `generated/gen-duplicate-ids` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 0.07 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-footnotes-ok` | generated | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 2/2 | 0.04 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-item-not-in-manifest` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 0.10 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-latin1-declared` | generated | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 0.08 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-latin1-undeclared` | generated | error | yes | yes | yes | 2/3 | 1/1 | 1/1 | 3/3 | 0/0 | 0.09 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff, input-repair |
| `generated/gen-missing-ncx` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 0/0 | 0/0 | 0.10 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-unterminated-tag` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 0.09 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `generated/gen-wrong-media-types` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 0.10 | 1.00 | 0/0/0/0 | 20/2 | style-lost, calibre-header-diff |
| `local/hertmans` | local | valid | yes | yes | yes | 20/20 | 28/28 | 28/28 | 9/9 | 0/0 | 0.83 | 1.00 | 0/0/0/0 | 54/104 | calibre-header-diff |
| `real/gutenberg/pg10450` | pg | valid | yes | yes | yes | 18/18 | 31/31 | 31/31 | 30/30 | 30/30 | 0.62 | 1.00 | 0/0/0/0 | 61/248 | calibre-header-diff |
| `real/gutenberg/pg11660` | pg | valid | yes | yes | yes | 6/6 | 27/27 | 27/27 | 21/21 | 17/17 | 0.61 | 1.00 | 0/0/0/0 | 50/48 | calibre-header-diff |
| `real/gutenberg/pg11993` | pg | valid | yes | yes | yes | 5/5 | 5/5 | 5/5 | 48/48 | 42/42 | 0.65 | 1.00 | 0/0/0/0 | 43/38 | calibre-header-diff |
| `real/gutenberg/pg12215` | pg | valid | yes | yes | yes | 19/19 | 72/72 | 72/72 | 20/20 | 85/85 | 0.78 | 1.00 | 0/0/0/0 | 44/46 | calibre-header-diff |
| `real/gutenberg/pg14658` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 14/14 | 9/9 | 0.61 | 1.00 | 0/0/0/0 | 46/67 | calibre-header-diff |
| `real/gutenberg/pg15228` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 116/116 | 0/0 | 0.67 | 1.00 | 0/0/0/0 | 48/39 | calibre-header-diff |
| `real/gutenberg/pg16113` | pg | valid | yes | yes | yes | 20/20 | 18/18 | 35/35 | 29/29 | 34/34 | 0.70 | 1.00 | 1/0/0/0 | 61/288 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg16578` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 30/30 | 0/0 | 0.68 | 1.00 | 0/0/0/0 | 45/39 | calibre-header-diff |
| `real/gutenberg/pg16866` | pg | valid | yes | yes | yes | 7/7 | 1/1 | 1/1 | 5/5 | 0/0 | 0.66 | 1.00 | 0/0/0/0 | 39/39 | calibre-header-diff |
| `real/gutenberg/pg17016` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 23/23 | 19/19 | 0.66 | 0.99 | 0/0/0/0 | 55/46 | calibre-header-diff |
| `real/gutenberg/pg1713` | pg | valid | yes | yes | yes | 8/8 | 1/1 | 1/1 | 45/45 | 39/39 | 0.78 | 1.00 | 0/0/0/0 | 43/46 | calibre-header-diff |
| `real/gutenberg/pg17250` | pg | valid | yes | yes | yes | 4/4 | 5/5 | 5/5 | 43/43 | 24/24 | 0.58 | 1.00 | 0/0/0/0 | 47/60 | calibre-header-diff |
| `real/gutenberg/pg17721` | pg | valid | yes | yes | yes | 7/7 | 3/3 | 5/5 | 41/41 | 62/62 | 0.58 | 0.98 | 0/0/0/0 | 60/77 | calibre-header-diff |
| `real/gutenberg/pg1816` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 10/10 | 6/6 | 0.78 | 1.00 | 0/0/0/0 | 41/45 | calibre-header-diff |
| `real/gutenberg/pg18196` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 25/25 | 0/0 | 0.66 | 1.00 | 0/0/0/3 | 46/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg18214` | pg | valid | yes | yes | yes | 3/3 | 7/7 | 7/7 | 6/6 | 0/0 | 0.63 | 0.99 | 1/0/0/0 | 50/41 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg19246` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 1/1 | 18/18 | 0.83 | 1.00 | 0/0/0/0 | 49/50 | calibre-header-diff |
| `real/gutenberg/pg2037` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 15/15 | 0/0 | 0.51 | 1.00 | 0/0/0/0 | 37/34 | calibre-header-diff |
| `real/gutenberg/pg21005` | pg | valid | yes | yes | yes | 6/6 | 10/10 | 10/10 | 42/42 | 27/27 | 0.61 | 1.00 | 1/0/0/0 | 87/44 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg2175` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 6/6 | 4/4 | 0.78 | 1.00 | 0/0/0/0 | 44/46 | calibre-header-diff |
| `real/gutenberg/pg21853` | pg | valid | yes | yes | yes | 30/30 | 33/33 | 140/140 | 161/161 | 1034/1034 | 0.59 | 1.00 | 0/0/0/0 | 96/282 | calibre-header-diff |
| `real/gutenberg/pg22088` | pg | valid | yes | yes | yes | 8/8 | 1/1 | 1/1 | 55/55 | 73/73 | 0.58 | 0.99 | 0/0/0/0 | 53/46 | calibre-header-diff |
| `real/gutenberg/pg22096` | pg | valid | yes | yes | yes | 4/4 | 92/92 | 93/93 | 55/55 | 43/43 | 0.61 | 1.00 | 0/0/0/0 | 96/47 | calibre-header-diff |
| `real/gutenberg/pg22110` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 2/2 | 0/0 | 0.64 | 1.00 | 0/0/0/0 | 42/37 | calibre-header-diff |
| `real/gutenberg/pg23092` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 3/3 | 21/21 | 34/34 | 0.67 | 1.00 | 0/0/0/0 | 74/72 | calibre-header-diff |
| `real/gutenberg/pg23378` | pg | valid | yes | yes | yes | 5/5 | 7/7 | 7/7 | 34/34 | 22/22 | 0.70 | 1.00 | 0/0/0/0 | 43/83 | calibre-header-diff |
| `real/gutenberg/pg27367` | pg | valid | yes | yes | yes | 8/8 | 226/226 | 342/342 | 90/90 | 174/174 | 0.58 | 0.99 | 0/0/0/0 | 121/81 | calibre-header-diff |
| `real/gutenberg/pg27703` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 16/16 | 34/34 | 0.85 | 1.00 | 0/0/0/0 | 80/116 | calibre-header-diff |
| `real/gutenberg/pg28050` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 18/18 | 4/4 | 0.61 | 0.99 | 0/0/0/0 | 44/39 | calibre-header-diff |
| `real/gutenberg/pg29047` | pg | valid | yes | yes | yes | 8/8 | 23/23 | 23/23 | 57/57 | 91/91 | 0.63 | 0.97 | 1/0/0/0 | 126/69 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29340` | pg | valid | yes | yes | yes | 30/30 | 54/54 | 54/54 | 68/68 | 198/198 | 0.68 | 1.00 | 2/0/0/0 | 75/339 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29559` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 3/3 | 5/5 | 2/2 | 0.64 | 1.00 | 0/0/0/0 | 51/59 | calibre-header-diff |
| `real/gutenberg/pg29815` | pg | valid | yes | yes | yes | 4/4 | 2/2 | 2/2 | 28/28 | 237/237 | 0.62 | 1.00 | 0/0/0/0 | 58/52 | calibre-header-diff |
| `real/gutenberg/pg30274` | pg | valid | yes | yes | yes | 8/8 | 9/9 | 9/9 | 29/29 | 113/113 | 0.61 | 1.00 | 0/0/0/0 | 70/47 | calibre-header-diff |
| `real/gutenberg/pg3030` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 30/30 | 28/28 | 0.78 | 1.00 | 0/0/0/0 | 43/46 | calibre-header-diff |
| `real/gutenberg/pg30963` | pg | valid | yes | yes | yes | 3/3 | 8/8 | 8/8 | 9/9 | 0/0 | 0.61 | 1.00 | 0/0/0/0 | 51/47 | calibre-header-diff |
| `real/gutenberg/pg31085` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 61/61 | 82/82 | 0.63 | 1.00 | 0/0/0/0 | 59/55 | calibre-header-diff |
| `real/gutenberg/pg31099` | pg | valid | yes | yes | yes | 9/9 | 6/6 | 6/6 | 25/25 | 0/0 | 0.51 | 1.00 | 0/0/0/0 | 52/49 | calibre-header-diff |
| `real/gutenberg/pg3193` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 14/14 | 9/9 | 0.76 | 0.96 | 0/0/0/0 | 41/43 | calibre-header-diff |
| `real/gutenberg/pg34176` | pg | valid | yes | yes | yes | 284/284 | 279/279 | 280/280 | 23/23 | 890/890 | 0.64 | 1.00 | 0/0/0/0 | 83/3677 | calibre-header-diff |
| `real/gutenberg/pg34377` | pg | valid | yes | yes | yes | 5/5 | 4/4 | 4/4 | 22/22 | 31/31 | 0.64 | 0.99 | 0/0/0/0 | 60/59 | calibre-header-diff |
| `real/gutenberg/pg34433` | pg | valid | yes | yes | yes | 4/4 | 125/125 | 125/125 | 12/12 | 6/6 | 0.50 | 0.98 | 1/0/0/0 | 93/74 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg36578` | pg | valid | yes | yes | yes | 6/6 | 8/8 | 8/8 | 26/26 | 13/13 | 0.73 | 1.00 | 0/0/0/0 | 48/48 | calibre-header-diff |
| `real/gutenberg/pg36902` | pg | valid | yes | yes | yes | 3/3 | 9/9 | 9/9 | 7/7 | 154/154 | 0.69 | 1.00 | 0/0/0/0 | 57/58 | calibre-header-diff |
| `real/gutenberg/pg37394` | pg | valid | yes | yes | yes | 5/5 | 40/40 | 40/40 | 169/169 | 88/88 | 0.63 | 1.00 | 0/0/0/0 | 66/59 | calibre-header-diff |
| `real/gutenberg/pg41097` | pg | valid | yes | yes | yes | 4/4 | 11/11 | 11/11 | 33/33 | 39/39 | 0.58 | 0.97 | 0/0/0/0 | 58/54 | calibre-header-diff |
| `real/gutenberg/pg43593` | pg | valid | yes | yes | yes | 13/13 | 24/24 | 24/24 | 25/25 | 399/399 | 0.68 | 1.00 | 0/0/0/0 | 92/100 | calibre-header-diff |
| `real/gutenberg/pg44342` | pg | valid | yes | yes | yes | 3/3 | 23/23 | 47/47 | 6/6 | 17/17 | 0.74 | 0.99 | 0/0/0/0 | 63/69 | calibre-header-diff |
| `real/gutenberg/pg44385` | pg | valid | yes | yes | yes | 17/17 | 1/1 | 1/1 | 30/30 | 14/14 | 0.78 | 1.00 | 0/0/0/0 | 47/50 | calibre-header-diff |
| `real/gutenberg/pg44953` | pg | valid | yes | yes | yes | 19/19 | 33/33 | 33/33 | 28/28 | 32/32 | 0.61 | 1.00 | 0/0/0/1 | 88/303 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg45731` | pg | valid | yes | yes | yes | 6/6 | 41/41 | 43/43 | 270/270 | 182/182 | 0.64 | 1.00 | 0/0/0/0 | 83/56 | calibre-header-diff |
| `real/gutenberg/pg461` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 63/63 | 48/48 | 0.74 | 1.00 | 0/0/0/0 | 49/38 | calibre-header-diff |
| `real/gutenberg/pg47151` | pg | valid | yes | yes | yes | 6/6 | 15/15 | 15/15 | 22/22 | 455/455 | 0.62 | 0.99 | 0/0/0/0 | 86/59 | calibre-header-diff |
| `real/gutenberg/pg48218` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 10/10 | 233/233 | 0.73 | 0.90 | 1/0/0/0 | 45/54 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg48323` | pg | valid | yes | yes | yes | 25/25 | 2/2 | 2/2 | 20/20 | 1484/1484 | 0.64 | 1.00 | 0/0/0/0 | 92/91 | calibre-header-diff |
| `real/gutenberg/pg4865` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 4/4 | 0/0 | 0.67 | 1.00 | 0/0/0/0 | 42/39 | calibre-header-diff |
| `real/gutenberg/pg49350` | pg | valid | yes | yes | yes | 5/5 | 9/9 | 9/9 | 36/36 | 40/40 | 0.61 | 0.99 | 0/0/0/0 | 60/52 | calibre-header-diff |
| `real/gutenberg/pg49505` | pg | valid | yes | yes | yes | 38/38 | 51/51 | 51/51 | 28/28 | 676/676 | 0.71 | 1.00 | 0/0/0/0 | 122/96 | calibre-header-diff |
| `real/gutenberg/pg50820` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 8/8 | 4/4 | 0.78 | 1.00 | 0/0/0/0 | 56/58 | calibre-header-diff |
| `real/gutenberg/pg51700` | pg | valid | yes | yes | yes | 20/20 | 35/35 | 50/50 | 3/3 | 55/55 | 0.77 | 1.00 | 0/0/0/0 | 47/283 | calibre-header-diff |
| `real/gutenberg/pg52303` | pg | valid | yes | yes | yes | 35/35 | 177/177 | 185/185 | 42/42 | 4517/4517 | 0.74 | 1.00 | 0/0/0/0 | 285/323 | calibre-header-diff |
| `real/gutenberg/pg52657` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 4/4 | 0/0 | 0.69 | 1.00 | 0/0/0/0 | 50/59 | calibre-header-diff |
| `real/gutenberg/pg53626` | pg | valid | yes | yes | yes | 29/29 | 3/3 | 3/3 | 20/20 | 3956/3956 | 0.79 | 0.99 | 0/0/0/0 | 134/166 | calibre-header-diff |
| `real/gutenberg/pg54611` | pg | valid | yes | yes | yes | 36/36 | 2/2 | 2/2 | 42/42 | 1986/1986 | 0.71 | 1.00 | 0/0/0/0 | 172/156 | calibre-header-diff |
| `real/gutenberg/pg5513` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 6/6 | 0/0 | 0.67 | 1.00 | 0/0/0/0 | 40/39 | calibre-header-diff |
| `real/gutenberg/pg5578` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 9/9 | 0/0 | 0.67 | 1.00 | 0/0/0/0 | 40/39 | calibre-header-diff |
| `real/gutenberg/pg55919` | pg | valid | yes | yes | yes | 45/45 | 58/58 | 58/58 | 16/16 | 1077/1077 | 0.72 | 0.98 | 0/0/0/0 | 106/484 | calibre-header-diff |
| `real/gutenberg/pg57791` | pg | valid | yes | yes | yes | 22/22 | 14/14 | 14/14 | 21/21 | 37/37 | 0.68 | 1.00 | 0/0/0/0 | 109/113 | calibre-header-diff |
| `real/gutenberg/pg58062` | pg | valid | yes | yes | yes | 22/22 | 1/1 | 1/1 | 598/598 | 2257/2257 | 0.77 | 1.00 | 0/0/0/0 | 62/115 | calibre-header-diff |
| `real/gutenberg/pg58344` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 16/16 | 16/16 | 0.29 | 0.99 | 0/0/0/0 | 41/28 | style-lost, calibre-header-diff |
| `real/gutenberg/pg59227` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 4/4 | 25/25 | 10/10 | 0.74 | 1.00 | 0/0/0/0 | 47/58 | calibre-header-diff |
| `real/gutenberg/pg60297` | pg | valid | yes | yes | yes | 4/4 | 7/7 | 7/7 | 7/7 | 0/0 | 0.81 | 1.00 | 0/0/0/0 | 62/89 | calibre-header-diff |
| `real/gutenberg/pg6072` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 32/32 | 0/0 | 0.66 | 1.00 | 0/0/0/0 | 40/39 | calibre-header-diff |
| `real/gutenberg/pg60903` | pg | valid | yes | yes | yes | 5/5 | 2/2 | 2/2 | 40/40 | 0/0 | 0.42 | 0.99 | 0/0/0/0 | 70/200 | style-lost, calibre-header-diff |
| `real/gutenberg/pg61267` | pg | valid | yes | yes | yes | 16/16 | 128/128 | 128/128 | 191/191 | 1025/1025 | 0.74 | 0.98 | 0/0/0/0 | 239/373 | calibre-header-diff |
| `real/gutenberg/pg61348` | pg | valid | yes | yes | yes | 22/22 | 10/10 | 10/10 | 15/15 | 20/20 | 0.72 | 1.00 | 1/0/0/0 | 105/97 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg62947` | pg | valid | yes | yes | yes | 22/22 | 57/57 | 57/57 | 22/22 | 86/86 | 0.58 | 0.99 | 1/0/0/0 | 70/69 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg63372` | pg | valid | yes | yes | yes | 26/26 | 104/104 | 126/128 | 129/129 | 1011/1011 | 0.90 | 0.99 | 6/0/0/0 | 170/353 | images-misreferenced, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg64210` | pg | valid | yes | yes | yes | 17/17 | 3/3 | 3/3 | 247/247 | 1201/1201 | 0.81 | 1.00 | 0/0/0/0 | 75/79 | calibre-header-diff |
| `real/gutenberg/pg6466` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 12/12 | 0/0 | 0.74 | 1.00 | 0/0/0/0 | 42/39 | calibre-header-diff |
| `real/gutenberg/pg6568` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 53/53 | 0/0 | 0.70 | 1.00 | 0/0/0/1 | 45/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg66997` | pg | valid | yes | yes | yes | 56/56 | 3/3 | 52/52 | 56/56 | 51/51 | 0.85 | 1.00 | 0/0/0/0 | 65/63 | calibre-header-diff |
| `real/gutenberg/pg67108` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 2/2 | 0/0 | 0.68 | 1.00 | 0/0/0/0 | 53/103 | calibre-header-diff |
| `real/gutenberg/pg67331` | pg | valid | yes | yes | yes | 35/35 | 6/6 | 12/12 | 35/35 | 558/558 | 0.66 | 1.00 | 0/0/0/0 | 79/68 | calibre-header-diff |
| `real/gutenberg/pg6795` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 13/13 | 18/18 | 0.80 | 0.97 | 0/0/0/0 | 42/43 | calibre-header-diff |
| `real/gutenberg/pg69052` | pg | valid | yes | yes | yes | 33/33 | 7/7 | 7/7 | 28/28 | 5/5 | 0.61 | 1.00 | 0/0/0/0 | 66/74 | calibre-header-diff |
| `real/gutenberg/pg69443` | pg | valid | yes | yes | yes | 3/3 | 2/2 | 2/2 | 26/26 | 17/17 | 0.69 | 1.00 | 0/0/0/0 | 40/36 | calibre-header-diff |
| `real/gutenberg/pg70584` | pg | valid | yes | yes | yes | 12/12 | 2/2 | 2/2 | 12/12 | 7/7 | 0.65 | 1.00 | 2/0/0/0 | 56/65 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7115` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 59/59 | 0/0 | 0.65 | 1.00 | 0/0/0/0 | 44/39 | calibre-header-diff |
| `real/gutenberg/pg71277` | pg | valid | yes | yes | yes | 18/18 | 1/1 | 1/1 | 90/90 | 13/13 | 0.68 | 1.00 | 1/0/0/0 | 72/152 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg71842` | pg | valid | yes | yes | yes | 17/17 | 254/254 | 254/254 | 35/35 | 1753/1753 | 0.69 | 1.00 | 2/0/0/0 | 237/89 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7199` | pg | valid | yes | yes | yes | 3/3 | 27/27 | 27/27 | 10/10 | 26/26 | 0.78 | 1.00 | 0/0/0/0 | 40/42 | calibre-header-diff |
| `real/gutenberg/pg72234` | pg | valid | yes | yes | yes | 3/3 | 3/3 | 3/3 | 2/2 | 0/0 | 0.61 | 1.00 | 0/0/0/0 | 43/50 | calibre-header-diff |
| `real/gutenberg/pg7237` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 65/65 | 59/59 | 0.75 | 0.99 | 0/0/0/0 | 44/46 | calibre-header-diff |
| `real/gutenberg/pg72476` | pg | valid | yes | yes | yes | 46/46 | 2/2 | 2/2 | 108/108 | 297/297 | 0.85 | 1.00 | 0/0/0/0 | 114/130 | calibre-header-diff |
| `real/gutenberg/pg74064` | pg | valid | yes | yes | yes | 41/41 | 14/14 | 14/14 | 59/59 | 41/41 | 0.59 | 1.00 | 0/0/0/0 | 77/79 | calibre-header-diff |
| `real/gutenberg/pg74759` | pg | valid | yes | yes | yes | 11/11 | 1/1 | 1/1 | 12/12 | 8/8 | 0.61 | 1.00 | 0/0/0/0 | 51/63 | calibre-header-diff |
| `real/gutenberg/pg77864` | pg | valid | yes | yes | yes | 14/14 | 1/1 | 1/1 | 13/13 | 21/21 | 0.69 | 1.00 | 0/0/0/0 | 49/55 | calibre-header-diff |
| `real/gutenberg/pg7906` | pg | valid | yes | yes | yes | 11/11 | 12/12 | 27/27 | 4/4 | 24/24 | 0.80 | 1.00 | 0/0/0/0 | 43/147 | calibre-header-diff |
| `real/gutenberg/pg8932` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 29/29 | 0/0 | 0.66 | 1.00 | 0/0/0/4 | 42/39 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/a-e-w-mason_the-four-feathers` | se | valid | yes | yes | yes | 42/42 | 3/3 | 6/6 | 42/42 | 3/3 | 0.77 | 1.00 | 0/0/0/0 | 58/81 | calibre-header-diff |
| `real/…dard-ebooks/a-e-w-mason_the-house-of-the-arrow` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 64/86 | calibre-header-diff |
| `real/…ndard-ebooks/agatha-christie_partners-in-crime` | se | valid | yes | yes | yes | 21/21 | 3/3 | 6/6 | 33/33 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 59/78 | calibre-header-diff |
| `real/standard-ebooks/ameen-rihani_the-book-of-khalid` | se | valid | yes | yes | yes | 41/41 | 3/3 | 6/6 | 41/41 | 11/11 | 0.78 | 1.00 | 0/0/0/0 | 68/87 | calibre-header-diff |
| `real/…dard-ebooks/anna-katharine-green_hand-and-ring` | se | valid | yes | yes | yes | 53/53 | 5/5 | 10/10 | 53/53 | 3/3 | 0.78 | 1.00 | 0/0/0/0 | 75/101 | calibre-header-diff |
| `real/…oks/anna-katharine-green_the-sword-of-damocles` | se | valid | yes | yes | yes | 59/59 | 3/3 | 6/6 | 59/59 | 3/3 | 0.79 | 1.00 | 0/0/0/0 | 87/116 | calibre-header-diff |
| `real/…ard-ebooks/anne-parrish_the-perennial-bachelor` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 55/81 | calibre-header-diff |
| `real/…dard-ebooks/anthony-trollope_dr-wortles-school` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 49/69 | calibre-header-diff |
| `real/…rd-ebooks/arthur-b-reeve_craig-kennedy-stories` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 58/78 | calibre-header-diff |
| `real/…ks/arthur-conan-doyle_brigadier-gerard-stories` | se | valid | yes | yes | yes | 21/21 | 3/3 | 6/6 | 23/23 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 46/66 | calibre-header-diff |
| `real/…d-ebooks/arthur-ransome_racundras-first-cruise` | se | valid | yes | yes | yes | 37/37 | 37/37 | 44/44 | 37/37 | 39/39 | 0.78 | 1.00 | 0/0/0/0 | 58/76 | calibre-header-diff |
| `real/…rd-ebooks/c-h-spurgeon_the-art-of-illustration` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 7/7 | 0.78 | 0.99 | 0/0/0/0 | 56/73 | calibre-header-diff |
| `real/…therine-louisa-pirkis_a-bride-of-a-summers-day` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 53/75 | calibre-header-diff |
| `real/…d-ebooks/catherine-louisa-pirkis_short-fiction` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 32/32 | 1/1 | 0.79 | 1.00 | 0/0/0/0 | 64/78 | calibre-header-diff |
| `real/…e-experiences-of-loveday-brooke-lady-detective` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 51/71 | calibre-header-diff |
| `real/standard-ebooks/charles-brockden-brown_wieland` | se | valid | yes | yes | yes | 35/35 | 3/3 | 6/6 | 35/35 | 9/9 | 0.76 | 1.00 | 0/0/0/0 | 60/80 | calibre-header-diff |
| `real/standard-ebooks/charles-dickens_barnaby-rudge` | se | valid | yes | yes | yes | 88/88 | 3/3 | 6/6 | 88/88 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 46/67 | calibre-header-diff |
| `real/…oks/charles-dickens_the-mystery-of-edwin-drood` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 30/30 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 62/81 | calibre-header-diff |
| `real/standard-ebooks/charles-kingsley_hypatia` | se | valid | yes | yes | yes | 38/38 | 3/3 | 6/6 | 38/38 | 13/13 | 0.77 | 1.00 | 0/0/0/0 | 66/83 | calibre-header-diff |
| `real/…arlotte-m-yonge_the-clever-woman-of-the-family` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 59/83 | calibre-header-diff |
| `real/…s/charlotte-perkins-gilman_moving-the-mountain` | se | valid | yes | yes | yes | 18/18 | 3/3 | 6/6 | 18/18 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 45/69 | calibre-header-diff |
| `real/standard-ebooks/claude-mckay_banjo` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 57/80 | calibre-header-diff |
| `real/…ks/d-l-moody_the-way-to-god-and-how-to-find-it` | se | valid | yes | yes | yes | 16/16 | 3/3 | 6/6 | 16/16 | 5/5 | 0.77 | 0.99 | 0/0/0/0 | 57/78 | calibre-header-diff |
| `real/…d-ebooks/david-hume_a-treatise-of-human-nature` | se | valid | yes | yes | yes | 113/113 | 3/3 | 6/6 | 113/113 | 187/187 | 0.80 | 1.00 | 0/0/0/0 | 62/80 | calibre-header-diff |
| `real/standard-ebooks/dornford-yates_blind-corner` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 57/76 | calibre-header-diff |
| `real/standard-ebooks/dornford-yates_perishable-goods` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 58/80 | calibre-header-diff |
| `real/…ayers_robert-eustace_the-documents-in-the-case` | se | valid | yes | yes | yes | 61/61 | 3/3 | 6/6 | 61/61 | 5/5 | 0.78 | 0.99 | 0/0/0/0 | 78/90 | calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_deadlock` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 45/66 | calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_interim` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 47/72 | calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_oberland` | se | valid | yes | yes | yes | 16/16 | 3/3 | 6/6 | 16/16 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 45/71 | calibre-header-diff |
| `real/…d-ebooks/dorothy-m-richardson_revolving-lights` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 48/74 | calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_the-trap` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 49/76 | calibre-header-diff |
| `real/…ks/e-nesbit_beautiful-stories-from-shakespeare` | se | valid | yes | yes | yes | 27/27 | 3/3 | 6/6 | 27/27 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 50/79 | calibre-header-diff |
| `real/…d-ebooks/edgar-rice-burroughs_pirates-of-venus` | se | valid | yes | yes | yes | 18/18 | 3/3 | 6/6 | 18/18 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 50/69 | calibre-header-diff |
| `real/standard-ebooks/edgar-saltus_short-fiction` | se | valid | yes | yes | yes | 37/37 | 3/3 | 6/6 | 167/167 | 15/15 | 0.79 | 1.00 | 0/0/0/0 | 90/110 | calibre-header-diff |
| `real/…andard-ebooks/edgar-saltus_the-perfume-of-eros` | se | valid | yes | yes | yes | 26/26 | 3/3 | 6/6 | 26/26 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 46/66 | calibre-header-diff |
| `real/…-burke_reflections-on-the-revolution-in-france` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 123/123 | 0.75 | 0.92 | 0/0/0/0 | 62/80 | calibre-header-diff |
| `real/…ebooks/ford-madox-ford_the-fifth-queen-crowned` | se | valid | yes | yes | yes | 32/32 | 3/3 | 6/6 | 32/32 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 55/83 | calibre-header-diff |
| `real/…oks/franklin-w-dixon_the-great-airport-mystery` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 46/66 | calibre-header-diff |
| `real/standard-ebooks/george-eliot_romola` | se | valid | yes | yes | yes | 83/83 | 3/3 | 6/6 | 83/83 | 65/65 | 0.77 | 1.00 | 0/0/0/0 | 60/74 | calibre-header-diff |
| `real/…dard-ebooks/george-macdonald_if-i-had-a-father` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 1/1 | 0.86 | 1.00 | 0/0/0/0 | 60/83 | calibre-header-diff |
| `real/…ard-ebooks/george-macdonald_within-and-without` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 78/78 | 1/1 | 0.90 | 1.00 | 0/0/0/0 | 85/109 | calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-black-gang` | se | valid | yes | yes | yes | 22/22 | 3/3 | 6/6 | 22/22 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 49/71 | calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-final-count` | se | valid | yes | yes | yes | 19/19 | 3/3 | 6/6 | 19/19 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 50/69 | calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-third-round` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 48/69 | calibre-header-diff |
| `real/standard-ebooks/h-g-wells_the-wheels-of-chance` | se | valid | yes | yes | yes | 33/33 | 4/4 | 8/8 | 74/74 | 3/3 | 0.80 | 1.00 | 0/0/0/0 | 53/72 | calibre-header-diff |
| `real/standard-ebooks/harry-harrison_short-fiction` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 50/72 | calibre-header-diff |
| `real/…oks/henry-seton-merriman_barlasch-of-the-guard` | se | valid | yes | yes | yes | 36/36 | 3/3 | 6/6 | 36/36 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 54/81 | calibre-header-diff |
| `real/standard-ebooks/henry-seton-merriman_the-sowers` | se | valid | yes | yes | yes | 48/48 | 3/3 | 6/6 | 48/48 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 49/70 | calibre-header-diff |
| `real/…d-ebooks/henry-van-dyke-jr_the-house-of-rimmon` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 17/17 | 3/3 | 0.90 | 1.00 | 0/0/0/0 | 82/104 | calibre-header-diff |
| `real/…d-ebooks/herbert-gorman_the-place-called-dagon` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 43/43 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 44/71 | calibre-header-diff |
| `real/…d-ebooks/hilaire-belloc_the-cruise-of-the-nona` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 1/1 | 0.69 | 0.87 | 0/0/0/0 | 57/82 | calibre-header-diff |
| `real/…ooks/j-storer-clouston_the-man-from-the-clouds` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 64/87 | calibre-header-diff |
| `real/…rd-ebooks/james-branch-cabell_the-line-of-love` | se | valid | yes | yes | yes | 20/20 | 3/3 | 6/6 | 20/20 | 5/5 | 0.81 | 1.00 | 0/0/0/0 | 70/92 | calibre-header-diff |
| `real/standard-ebooks/jane-c-loudon_the-mummy` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 56/80 | calibre-header-diff |
| `real/standard-ebooks/john-donne_poetry` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 219/219 | 1/1 | 0.86 | 1.00 | 0/0/0/0 | 84/106 | calibre-header-diff |
| `real/standard-ebooks/john-gay_the-beggars-opera` | se | valid | yes | yes | yes | 13/13 | 71/71 | 142/142 | 23/23 | 69/69 | 0.89 | 1.00 | 0/0/0/0 | 90/118 | calibre-header-diff |
| `real/…books/john-meade-falkner_the-lost-stradivarius` | se | valid | yes | yes | yes | 24/24 | 3/3 | 6/6 | 24/24 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 54/85 | calibre-header-diff |
| `real/…-ebooks/john-newton_william-cowper_olney-hymns` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 383/383 | 67/67 | 0.87 | 1.00 | 0/0/0/0 | 68/80 | calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_chance` | se | valid | yes | yes | yes | 23/23 | 3/3 | 6/6 | 23/23 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 56/80 | calibre-header-diff |
| `real/…h-conrad_ford-madox-ford_the-nature-of-a-crime` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.76 | 0.99 | 0/0/0/0 | 46/68 | calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_suspense` | se | valid | yes | yes | yes | 25/25 | 3/3 | 6/6 | 25/25 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 48/68 | calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-arrow-of-gold` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 58/84 | calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-rescue` | se | valid | yes | yes | yes | 55/55 | 3/3 | 6/6 | 55/55 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 56/85 | calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-rover` | se | valid | yes | yes | yes | 23/23 | 3/3 | 6/6 | 23/23 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 53/84 | calibre-header-diff |
| `real/…s/joshua-slocum_sailing-alone-around-the-world` | se | valid | yes | yes | yes | 30/30 | 14/14 | 28/28 | 30/30 | 28/28 | 0.79 | 1.00 | 0/0/0/0 | 71/92 | calibre-header-diff |
| `real/…dard-ebooks/kahlil-gibran_jesus-the-son-of-man` | se | valid | yes | yes | yes | 83/83 | 3/3 | 6/6 | 83/83 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 52/72 | calibre-header-diff |
| `real/…arine-a-carl_with-the-empress-dowager-of-china` | se | valid | yes | yes | yes | 44/44 | 24/24 | 27/27 | 44/44 | 40/40 | 0.79 | 0.99 | 0/0/0/0 | 65/85 | calibre-header-diff |
| `real/standard-ebooks/maria-lowell_poetry` | se | valid | yes | yes | yes | 6/6 | 3/3 | 6/6 | 25/25 | 3/3 | 0.83 | 1.00 | 0/0/0/0 | 59/77 | calibre-header-diff |
| `real/…s/marie-belloc-lowndes_the-chink-in-the-armour` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 31/31 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 51/76 | calibre-header-diff |
| `real/…-ebooks/marmaduke-pickthall_said-the-fisherman` | se | valid | yes | yes | yes | 55/55 | 3/3 | 6/6 | 55/55 | 9/9 | 0.76 | 1.00 | 0/0/0/0 | 58/77 | calibre-header-diff |
| `real/…d-ebooks/mary-augusta-ward_lady-roses-daughter` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 51/73 | calibre-header-diff |
| `real/…rd-ebooks/mary-p-hamlin_george-arliss_hamilton` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 1/1 | 0.86 | 1.00 | 0/0/0/0 | 73/99 | calibre-header-diff |
| `real/…rd-ebooks/mourning-dove_cogewea-the-half-blood` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 119/119 | 0.79 | 1.00 | 0/0/0/0 | 76/100 | calibre-header-diff |
| `real/standard-ebooks/noel-coward_hay-fever` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 1/1 | 0.85 | 1.00 | 0/0/0/0 | 68/100 | calibre-header-diff |
| `real/…ndard-ebooks/noel-loomis_short-science-fiction` | se | valid | yes | yes | yes | 13/13 | 3/3 | 6/6 | 13/13 | 1/1 | 0.75 | 1.00 | 0/0/0/0 | 49/71 | calibre-header-diff |
| `real/…andard-ebooks/norman-angell_the-great-illusion` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 31/31 | 267/267 | 0.80 | 1.00 | 0/0/0/0 | 57/69 | calibre-header-diff |
| `real/…ndard-ebooks/olaf-stapledon_last-and-first-men` | se | valid | yes | yes | yes | 24/24 | 7/7 | 14/14 | 80/80 | 5/5 | 0.79 | 1.00 | 0/0/0/0 | 52/70 | calibre-header-diff |
| `real/…d-ebooks/p-g-wodehouse_the-adventures-of-sally` | se | valid | yes | yes | yes | 22/22 | 3/3 | 6/6 | 59/59 | 1/1 | 0.79 | 1.00 | 0/0/0/0 | 55/75 | calibre-header-diff |
| `real/…ard-ebooks/pauline-e-hopkins_contending-forces` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.79 | 1.00 | 0/0/0/0 | 81/112 | calibre-header-diff |
| `real/standard-ebooks/pauline-e-hopkins_of-one-blood` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 54/80 | calibre-header-diff |
| `real/standard-ebooks/ring-lardner_fred-gross-stories` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.84 | 0.99 | 0/0/0/0 | 50/76 | calibre-header-diff |
| `real/…ebooks/ring-lardner_george-s-kaufman_june-moon` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.86 | 1.00 | 0/0/0/0 | 67/98 | calibre-header-diff |
| `real/standard-ebooks/ring-lardner_gullibles-travels` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 28/28 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 46/68 | calibre-header-diff |
| `real/standard-ebooks/ring-lardner_short-fiction` | se | valid | yes | yes | yes | 80/80 | 3/3 | 6/6 | 203/203 | 115/115 | 0.78 | 1.00 | 0/0/0/0 | 74/86 | calibre-header-diff |
| `real/…ard-ebooks/robert-hugh-benson_the-necromancers` | se | valid | yes | yes | yes | 25/25 | 3/3 | 6/6 | 68/68 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 48/70 | calibre-header-diff |
| `real/standard-ebooks/robert-louis-stevenson_poetry` | se | valid | yes | yes | yes | 7/7 | 13/13 | 26/26 | 385/385 | 99/99 | 0.84 | 1.00 | 0/0/0/0 | 87/93 | calibre-header-diff |
| `real/…ard-ebooks/rudolph-fisher_the-walls-of-jericho` | se | valid | yes | yes | yes | 40/40 | 3/3 | 6/6 | 40/40 | 57/57 | 0.76 | 1.00 | 0/0/0/0 | 59/88 | calibre-header-diff |
| `real/…ard-ebooks/rudyard-kipling_captains-courageous` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 65/93 | calibre-header-diff |
| `real/…leridge_robert-southey_the-fall-of-robespierre` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 7/7 | 0.90 | 1.00 | 0/0/0/0 | 72/93 | calibre-header-diff |
| `real/…egfried-sassoon_memoirs-of-an-infantry-officer` | se | valid | yes | yes | yes | 14/14 | 3/3 | 6/6 | 50/50 | 1/1 | 0.78 | 1.00 | 0/0/0/0 | 53/72 | calibre-header-diff |
| `real/…e-roosevelt_a-book-lovers-holidays-in-the-open` | se | valid | yes | yes | yes | 23/23 | 5/5 | 9/9 | 23/23 | 10/10 | 0.81 | 1.00 | 0/0/0/0 | 86/113 | calibre-header-diff |
| `real/…s/w-e-b-du-bois_the-quest-of-the-silver-fleece` | se | valid | yes | yes | yes | 45/45 | 3/3 | 6/6 | 45/45 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 59/84 | calibre-header-diff |
| `real/…/w-h-davies_the-autobiography-of-a-super-tramp` | se | valid | yes | yes | yes | 40/40 | 3/3 | 6/6 | 40/40 | 1/1 | 0.78 | 0.99 | 0/0/0/0 | 46/67 | calibre-header-diff |
| `real/standard-ebooks/walter-white_flight` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 52/79 | calibre-header-diff |
| `real/…dard-ebooks/walter-white_the-fire-in-the-flint` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 53/83 | calibre-header-diff |
| `real/standard-ebooks/wilkie-collins_basil` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 42/42 | 3/3 | 0.78 | 1.00 | 0/0/0/0 | 61/79 | calibre-header-diff |
| `real/…ndard-ebooks/willa-cather_the-professors-house` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.77 | 1.00 | 0/0/0/0 | 56/82 | calibre-header-diff |
| `real/…rd-ebooks/winnifred-eaton-reeve_his-royal-nibs` | se | valid | yes | yes | yes | 33/33 | 3/3 | 6/6 | 33/33 | 1/1 | 0.76 | 1.00 | 0/0/0/0 | 50/80 | calibre-header-diff |
| `real/…-ebooks/yung-wing_my-life-in-china-and-america` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 36/36 | 3/3 | 0.78 | 0.99 | 0/0/0/0 | 61/77 | calibre-header-diff |

## Format: mobi

### 1. Summary

209 books were run for MOBI; 209 (100%) produced an output file. 209 of 209 (100%) converted books pass all three parser gates (mobitool, KindleUnpack, Calibre reader). 30 books carry at least one actionable gap (a book can carry several kinds): 29 have unported Calibre transform gaps (97%), 1 have input repair gaps (3%), 1 have writer bug gaps (3%); 32 category findings in total. Verdict: unported Calibre transform gaps affect the most books (97%), so the next effort should port the missing Calibre transforms, starting with `style-lost`. 179 of 209 books have no actionable gap and were fully evaluated. Mean style score on se+pg books: preservation 0.748 (n=200). Layout hygiene, pooled over 209 books (empty blocks / trailing breaks / whitespace runs / nbsp indents): output 241 / 1436 / 614888 / 16, input 167 / 1815 / 648461 / 16; 209 books have at least one in the output. Not counted in `layout-hygiene` (styled empty blocks / double trailing breaks / ambiguous nbsp indents): output 0 / 54 / 467, input 72 / 54 / 467. Not counted above (category findings): 419 informational.

### 2. Top gap categories by affected books

| # | category | books | % of books | description | kind |
|---|---|---|---|---|---|
| 1 | `style-lost` | 29 | 14% | Style score below 0.5, or the input has CSS rules and the output none | unported Calibre transform |
| 2 | `text-loss` | 1 | 0% | Spine items whose text did not survive conversion | transform or repair |
| 3 | `links-unresolved` | 1 | 0% | Internal links that no longer resolve | unported Calibre transform |
| 4 | `input-repair` | 1 | 0% | App failed or lost text on a malformed input Calibre converted anyway | input repair |

Informational, acceptable, harness and out-of-scope categories are not ranked here (`calibre-header-diff`, `images-resized`, `images-unextractable`, `spine-non-xhtml`, `layout-hygiene`, `app-clean-error`, `harness-error`, `fixed-layout-unsupported`), and nothing on a fixed-layout book is; they appear in the per-category breakdown and the per-book table. `text-loss` counts as `input repair` on books whose verdict is error/warning, otherwise as `writer bug`.

### 3. Books most needing a manual look in Kindle Previewer

Ranked: gate failure, then misreferenced images, then lowest style score, then text-loss, then unresolved links. Only books with an output file are eligible; fixed-layout books are not.

| # | book | corpus category | why |
|---|---|---|---|
| 1 | `real/standard-ebooks/noel-coward_hay-fever` | se | style score 0.15 |
| 2 | `real/standard-ebooks/mary-p-hamlin_george-arliss_hamilton` | se | style score 0.15 |
| 3 | `real/standard-ebooks/ring-lardner_george-s-kaufman_june-moon` | se | style score 0.18 |
| 4 | `real/standard-ebooks/george-macdonald_if-i-had-a-father` | se | style score 0.19 |
| 5 | `real/gutenberg/pg55919` | pg | style score 0.19 |

### 4. Gap categories by corpus category

| corpus category | books | `text-loss` | `images-unextractable` | `links-unresolved` | `style-lost` | `layout-hygiene` | `calibre-header-diff` | `input-repair` |
|---|---|---|---|---|---|---|---|---|
| generated | 8 |  |  |  |  | 8 | 8 | 1 |
| local | 1 |  |  |  |  | 1 | 1 |  |
| pg | 100 | 1 | 1 | 1 | 17 | 100 | 100 |  |
| se | 100 |  |  |  | 12 | 100 | 100 |  |
| **total** | 209 | 1 | 1 | 1 | 29 | 209 | 209 | 1 |

### 5. All books

| id | category | verdict | app ok | calibre ok | gate pass | text match/spine | images matched/referenced | image refs ok/total | toc matched/input | links resolved/total | style | device style | hygiene out (e/b/ws/nb) | css rules out/in | categories |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `generated/gen-duplicate-ids` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 1.00 | - | 0/0/9/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-footnotes-ok` | generated | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 2/2 | 1.00 | - | 0/0/7/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-item-not-in-manifest` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 1.00 | - | 0/0/8/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-latin1-declared` | generated | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 1.00 | - | 0/0/7/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-latin1-undeclared` | generated | error | yes | yes | yes | 2/3 | 1/1 | 1/1 | 3/3 | 0/0 | 1.00 | - | 0/0/7/0 | 0/2 | layout-hygiene, calibre-header-diff, input-repair |
| `generated/gen-missing-ncx` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 0/0 | 0/0 | 1.00 | - | 0/0/8/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-unterminated-tag` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 1.00 | - | 0/0/7/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `generated/gen-wrong-media-types` | generated | error | yes | yes | yes | 3/3 | 1/1 | 1/1 | 3/3 | 0/0 | 1.00 | - | 0/0/8/0 | 0/2 | layout-hygiene, calibre-header-diff |
| `local/hertmans` | local | valid | yes | yes | yes | 20/20 | 28/28 | 28/28 | 9/9 | 0/0 | 0.65 | - | 8/0/1282/0 | 0/104 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg10450` | pg | valid | yes | yes | yes | 18/18 | 31/31 | 31/31 | 30/30 | 30/30 | 0.60 | - | 2/0/1290/0 | 0/248 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg11660` | pg | valid | yes | yes | yes | 6/6 | 27/27 | 27/27 | 21/21 | 17/17 | 0.88 | - | 2/0/3817/0 | 0/48 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg11993` | pg | valid | yes | yes | yes | 5/5 | 5/5 | 5/5 | 48/48 | 42/42 | 0.83 | - | 3/0/1418/0 | 0/38 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg12215` | pg | valid | yes | yes | yes | 19/19 | 72/72 | 72/72 | 20/20 | 85/85 | 0.73 | - | 3/0/4595/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg14658` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 14/14 | 9/9 | 0.92 | - | 2/1/1155/2 | 0/67 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg15228` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 116/116 | 0/0 | 0.97 | - | 0/99/4938/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg16113` | pg | valid | yes | yes | yes | 20/20 | 18/18 | 35/35 | 29/29 | 34/34 | 0.48 | - | 2/0/1658/0 | 0/288 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg16578` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 30/30 | 0/0 | 0.96 | - | 0/139/3075/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg16866` | pg | valid | yes | yes | yes | 7/7 | 1/1 | 1/1 | 5/5 | 0/0 | 0.98 | - | 0/22/2773/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg17016` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 23/23 | 19/19 | 0.80 | - | 0/34/1711/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg1713` | pg | valid | yes | yes | yes | 8/8 | 1/1 | 1/1 | 45/45 | 39/39 | 0.93 | - | 0/1/3576/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg17250` | pg | valid | yes | yes | yes | 4/4 | 5/5 | 5/5 | 43/43 | 24/24 | 0.86 | - | 2/1/1128/0 | 0/60 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg17721` | pg | valid | yes | yes | yes | 7/7 | 3/3 | 5/5 | 41/41 | 62/62 | 0.66 | - | 0/0/2259/0 | 0/77 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg1816` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 10/10 | 6/6 | 0.86 | - | 0/0/545/0 | 0/45 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg18196` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 25/25 | 0/0 | 0.95 | - | 0/179/2904/4 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg18214` | pg | valid | yes | yes | yes | 3/3 | 7/7 | 7/7 | 6/6 | 0/0 | 0.69 | - | 1/0/280/0 | 0/41 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg19246` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 1/1 | 18/18 | 0.34 | - | 0/0/2350/0 | 0/50 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg2037` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 15/15 | 0/0 | 0.96 | - | 1/0/2969/0 | 0/34 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg21005` | pg | valid | yes | yes | yes | 6/6 | 10/10 | 10/10 | 42/42 | 27/27 | 0.96 | - | 2/0/4305/0 | 0/44 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg2175` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 6/6 | 4/4 | 0.98 | - | 0/0/2895/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg21853` | pg | valid | yes | yes | yes | 30/30 | 33/33 | 140/140 | 161/161 | 1034/1034 | 0.62 | - | 1/24/7659/0 | 0/282 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg22088` | pg | valid | yes | yes | yes | 8/8 | 1/1 | 1/1 | 55/55 | 73/73 | 0.84 | - | 2/3/4121/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg22096` | pg | valid | yes | yes | yes | 4/4 | 92/92 | 93/93 | 55/55 | 43/43 | 0.51 | - | 1/0/2127/0 | 0/47 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg22110` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 2/2 | 0/0 | 0.81 | - | 0/0/252/0 | 0/37 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg23092` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 3/3 | 21/21 | 34/34 | 0.75 | - | 0/0/1009/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg23378` | pg | valid | yes | yes | yes | 5/5 | 7/7 | 7/7 | 34/34 | 22/22 | 0.89 | - | 0/0/972/0 | 0/83 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg27367` | pg | valid | yes | yes | yes | 8/8 | 216/216 | 332/332 | 90/90 | 174/174 | 0.78 | - | 1/7/5415/0 | 0/81 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg27703` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 16/16 | 34/34 | 0.52 | - | 0/0/784/0 | 0/116 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg28050` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 18/18 | 4/4 | 0.83 | - | 0/0/402/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29047` | pg | valid | yes | yes | yes | 8/8 | 23/23 | 23/23 | 57/57 | 91/91 | 0.78 | - | 2/26/5279/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29340` | pg | valid | yes | yes | yes | 30/30 | 54/54 | 54/54 | 68/68 | 198/198 | 0.78 | - | 2/0/4678/0 | 0/339 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29559` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 3/3 | 5/5 | 2/2 | 0.87 | - | 0/0/377/0 | 0/59 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg29815` | pg | valid | yes | yes | yes | 4/4 | 2/2 | 2/2 | 28/28 | 237/237 | 0.51 | - | 0/10/1322/0 | 0/52 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg30274` | pg | valid | yes | yes | yes | 8/8 | 9/9 | 9/9 | 29/29 | 113/113 | 0.92 | - | 2/0/3427/0 | 0/47 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg3030` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 30/30 | 28/28 | 0.96 | - | 0/0/4069/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg30963` | pg | valid | yes | yes | yes | 3/3 | 8/8 | 8/8 | 9/9 | 0/0 | 0.89 | - | 0/1/869/0 | 0/47 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg31085` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 61/61 | 82/82 | 0.71 | - | 3/1/3682/0 | 0/55 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg31099` | pg | valid | yes | yes | yes | 9/9 | 6/6 | 6/6 | 25/25 | 0/0 | 0.51 | - | 1/0/6315/0 | 0/49 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg3193` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 14/14 | 9/9 | 0.71 | - | 0/0/1471/0 | 0/43 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg34176` | pg | valid | yes | yes | yes | 284/284 | 279/279 | 280/280 | 23/23 | 890/890 | 0.59 | - | 0/0/5430/0 | 0/3677 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg34377` | pg | valid | yes | yes | yes | 5/5 | 4/4 | 4/4 | 22/22 | 31/31 | 0.89 | - | 1/3/1372/0 | 0/59 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg34433` | pg | valid | yes | yes | yes | 4/4 | 125/125 | 125/125 | 12/12 | 6/6 | 0.54 | - | 3/46/838/0 | 0/74 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg36578` | pg | valid | yes | yes | yes | 6/6 | 8/8 | 8/8 | 26/26 | 13/13 | 0.53 | - | 2/10/2314/0 | 0/48 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg36902` | pg | valid | yes | yes | yes | 3/3 | 9/9 | 9/9 | 7/7 | 154/154 | 0.53 | - | 1/0/1427/0 | 0/58 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg37394` | pg | valid | yes | yes | yes | 5/5 | 40/40 | 40/40 | 169/169 | 88/88 | 0.78 | - | 0/2/1804/0 | 0/59 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg41097` | pg | valid | yes | yes | yes | 4/4 | 11/11 | 11/11 | 33/33 | 39/39 | 0.88 | - | 2/0/2774/0 | 0/54 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg43593` | pg | valid | yes | yes | yes | 13/13 | 24/24 | 24/24 | 25/25 | 399/399 | 0.54 | - | 2/9/9547/0 | 0/100 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg44342` | pg | valid | yes | yes | yes | 3/3 | 11/11 | 23/23 | 6/6 | 17/17 | 0.33 | - | 2/0/729/0 | 0/69 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg44385` | pg | valid | yes | yes | yes | 17/17 | 1/1 | 1/1 | 30/30 | 14/14 | 0.73 | - | 3/0/3626/0 | 0/50 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg44953` | pg | valid | yes | yes | yes | 19/19 | 33/33 | 33/33 | 28/28 | 32/32 | 0.59 | - | 2/2/1068/1 | 0/303 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg45731` | pg | valid | yes | yes | yes | 6/6 | 41/41 | 43/43 | 270/270 | 182/182 | 0.51 | - | 3/0/1749/0 | 0/56 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg461` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 63/63 | 48/48 | 0.56 | - | 2/40/2971/2 | 0/38 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg47151` | pg | valid | yes | yes | yes | 6/6 | 15/15 | 15/15 | 22/22 | 455/455 | 0.64 | - | 3/231/3631/0 | 0/59 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg48218` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 10/10 | 233/233 | 0.39 | - | 2/16/1000/0 | 0/54 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg48323` | pg | valid | yes | yes | yes | 25/25 | 2/2 | 2/2 | 20/20 | 1484/1484 | 0.42 | - | 20/0/8274/0 | 0/91 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg4865` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 4/4 | 0/0 | 0.91 | - | 0/6/591/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg49350` | pg | valid | yes | yes | yes | 5/5 | 9/9 | 9/9 | 36/36 | 40/40 | 0.87 | - | 2/0/2151/0 | 0/52 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg49505` | pg | valid | yes | yes | yes | 38/38 | 51/51 | 51/51 | 28/28 | 676/676 | 0.63 | - | 38/1/3607/0 | 0/96 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg50820` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 8/8 | 4/4 | 0.53 | - | 3/2/3694/0 | 0/58 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg51700` | pg | valid | yes | yes | yes | 20/20 | 35/35 | 50/50 | 3/3 | 55/55 | 0.41 | - | 2/0/547/0 | 0/283 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg52303` | pg | valid | yes | yes | yes | 35/35 | 177/177 | 185/185 | 42/42 | 4487/4487 | 0.26 | - | 2/0/16328/0 | 0/323 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg52657` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 4/4 | 0/0 | 0.72 | - | 3/1/241/0 | 0/59 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg53626` | pg | valid | yes | yes | yes | 29/29 | 3/3 | 3/3 | 20/20 | 3956/3956 | 0.33 | - | 2/0/21281/0 | 0/166 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg54611` | pg | valid | yes | yes | yes | 36/36 | 2/2 | 2/2 | 42/42 | 1986/1986 | 0.37 | - | 2/17/7772/0 | 0/156 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg5513` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 6/6 | 0/0 | 0.89 | - | 0/5/505/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg5578` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 9/9 | 0/0 | 0.94 | - | 0/18/1093/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg55919` | pg | valid | yes | yes | yes | 45/45 | 58/58 | 58/58 | 16/16 | 1077/1077 | 0.19 | - | 2/0/2820/0 | 0/484 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg57791` | pg | valid | yes | yes | yes | 22/22 | 14/14 | 14/14 | 21/21 | 37/37 | 0.47 | - | 0/0/1094/0 | 0/113 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg58062` | pg | valid | yes | yes | yes | 22/22 | 1/1 | 1/1 | 598/598 | 2257/2257 | 0.65 | - | 0/0/17570/2 | 0/115 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg58344` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 16/16 | 16/16 | 0.54 | - | 2/0/1144/0 | 0/28 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg59227` | pg | valid | yes | yes | yes | 4/4 | 3/3 | 4/4 | 25/25 | 10/10 | 0.36 | - | 0/1/1384/0 | 0/58 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg60297` | pg | valid | yes | yes | yes | 4/4 | 7/7 | 7/7 | 7/7 | 0/0 | 0.93 | - | 0/0/797/0 | 0/89 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg6072` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 32/32 | 0/0 | 0.98 | - | 0/112/3716/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg60903` | pg | valid | yes | yes | yes | 5/5 | 2/2 | 2/2 | 40/40 | 0/0 | 0.83 | - | 2/0/3382/0 | 0/200 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg61267` | pg | valid | yes | yes | yes | 16/16 | 128/128 | 128/128 | 191/191 | 1025/1025 | 0.47 | - | 2/0/7305/0 | 0/373 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg61348` | pg | valid | yes | yes | yes | 22/22 | 10/10 | 10/10 | 15/15 | 20/20 | 0.61 | - | 3/2/5874/0 | 0/97 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg62947` | pg | valid | yes | yes | yes | 22/22 | 57/57 | 57/57 | 22/22 | 86/86 | 0.87 | - | 3/0/2383/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg63372` | pg | valid | yes | yes | yes | 13/26 | 17/101 | 17/125 | 129/129 | 1007/1011 | 0.36 | - | 49/0/5159/0 | 0/353 | text-loss, images-unextractable, links-unresolved, style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg64210` | pg | valid | yes | yes | yes | 17/17 | 3/3 | 3/3 | 247/247 | 1201/1201 | 0.62 | - | 2/0/9442/0 | 0/79 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg6466` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 12/12 | 0/0 | 0.93 | - | 0/14/582/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg6568` | pg | valid | yes | yes | yes | 6/6 | 1/1 | 1/1 | 53/53 | 0/0 | 0.96 | - | 0/54/1713/1 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg66997` | pg | valid | yes | yes | yes | 56/56 | 3/3 | 52/52 | 56/56 | 51/51 | 0.29 | - | 2/0/3749/0 | 0/63 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg67108` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 2/2 | 0/0 | 0.65 | - | 3/0/206/0 | 0/103 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg67331` | pg | valid | yes | yes | yes | 35/35 | 6/6 | 12/12 | 35/35 | 558/558 | 0.66 | - | 2/6/3895/0 | 0/68 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg6795` | pg | valid | yes | yes | yes | 3/3 | 1/1 | 1/1 | 13/13 | 18/18 | 0.63 | - | 0/0/255/0 | 0/43 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg69052` | pg | valid | yes | yes | yes | 33/33 | 6/6 | 6/6 | 28/28 | 5/5 | 0.93 | - | 2/0/3252/0 | 0/74 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg69443` | pg | valid | yes | yes | yes | 3/3 | 2/2 | 2/2 | 26/26 | 17/17 | 0.60 | - | 3/0/588/0 | 0/36 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg70584` | pg | valid | yes | yes | yes | 12/12 | 2/2 | 2/2 | 12/12 | 7/7 | 0.65 | - | 2/2/586/0 | 0/65 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7115` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 59/59 | 0/0 | 0.94 | - | 0/233/2432/0 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg71277` | pg | valid | yes | yes | yes | 18/18 | 1/1 | 1/1 | 90/90 | 13/13 | 0.39 | - | 2/1/1829/0 | 0/152 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg71842` | pg | valid | yes | yes | yes | 17/17 | 254/254 | 254/254 | 35/35 | 1753/1753 | 0.27 | - | 3/0/9581/0 | 0/89 | style-lost, layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7199` | pg | valid | yes | yes | yes | 3/3 | 27/27 | 27/27 | 10/10 | 26/26 | 0.86 | - | 1/0/942/0 | 0/42 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg72234` | pg | valid | yes | yes | yes | 3/3 | 3/3 | 3/3 | 2/2 | 0/0 | 0.90 | - | 2/0/968/0 | 0/50 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7237` | pg | valid | yes | yes | yes | 4/4 | 1/1 | 1/1 | 65/65 | 59/59 | 0.86 | - | 0/0/1939/0 | 0/46 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg72476` | pg | valid | yes | yes | yes | 46/46 | 2/2 | 2/2 | 108/108 | 297/297 | 0.68 | - | 3/0/5073/0 | 0/130 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg74064` | pg | valid | yes | yes | yes | 41/41 | 13/13 | 13/13 | 59/59 | 41/41 | 0.70 | - | 2/0/2233/0 | 0/79 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg74759` | pg | valid | yes | yes | yes | 11/11 | 1/1 | 1/1 | 12/12 | 8/8 | 0.95 | - | 2/0/1731/0 | 0/63 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg77864` | pg | valid | yes | yes | yes | 14/14 | 1/1 | 1/1 | 13/13 | 21/21 | 0.65 | - | 2/0/671/0 | 0/55 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg7906` | pg | valid | yes | yes | yes | 11/11 | 12/12 | 27/27 | 4/4 | 24/24 | 0.79 | - | 0/0/283/0 | 0/147 | layout-hygiene, calibre-header-diff |
| `real/gutenberg/pg8932` | pg | valid | yes | yes | yes | 5/5 | 1/1 | 1/1 | 29/29 | 0/0 | 0.90 | - | 0/54/1124/4 | 0/39 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/a-e-w-mason_the-four-feathers` | se | valid | yes | yes | yes | 42/42 | 3/3 | 6/6 | 42/42 | 3/3 | 0.94 | - | 0/0/2435/0 | 0/81 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/a-e-w-mason_the-house-of-the-arrow` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.93 | - | 0/0/2976/0 | 0/86 | layout-hygiene, calibre-header-diff |
| `real/…ndard-ebooks/agatha-christie_partners-in-crime` | se | valid | yes | yes | yes | 21/21 | 3/3 | 6/6 | 33/33 | 1/1 | 0.88 | - | 0/0/3189/0 | 0/78 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/ameen-rihani_the-book-of-khalid` | se | valid | yes | yes | yes | 41/41 | 3/3 | 6/6 | 41/41 | 11/11 | 0.79 | - | 0/0/1289/0 | 0/87 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/anna-katharine-green_hand-and-ring` | se | valid | yes | yes | yes | 53/53 | 5/5 | 10/10 | 53/53 | 3/3 | 0.90 | - | 0/0/4884/0 | 0/101 | layout-hygiene, calibre-header-diff |
| `real/…oks/anna-katharine-green_the-sword-of-damocles` | se | valid | yes | yes | yes | 59/59 | 3/3 | 6/6 | 59/59 | 3/3 | 0.79 | - | 0/0/3643/0 | 0/116 | layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/anne-parrish_the-perennial-bachelor` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.86 | - | 0/0/2613/0 | 0/81 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/anthony-trollope_dr-wortles-school` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.93 | - | 0/0/1796/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/arthur-b-reeve_craig-kennedy-stories` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.96 | - | 0/0/2179/0 | 0/78 | layout-hygiene, calibre-header-diff |
| `real/…ks/arthur-conan-doyle_brigadier-gerard-stories` | se | valid | yes | yes | yes | 21/21 | 3/3 | 6/6 | 23/23 | 1/1 | 0.96 | - | 0/0/2391/0 | 0/66 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/arthur-ransome_racundras-first-cruise` | se | valid | yes | yes | yes | 37/37 | 37/37 | 44/44 | 37/37 | 39/39 | 0.83 | - | 0/0/820/0 | 0/76 | layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/c-h-spurgeon_the-art-of-illustration` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 7/7 | 0.56 | - | 0/0/601/0 | 0/73 | layout-hygiene, calibre-header-diff |
| `real/…therine-louisa-pirkis_a-bride-of-a-summers-day` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.94 | - | 0/0/1457/0 | 0/75 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/catherine-louisa-pirkis_short-fiction` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 32/32 | 1/1 | 0.91 | - | 0/0/1750/0 | 0/78 | layout-hygiene, calibre-header-diff |
| `real/…e-experiences-of-loveday-brooke-lady-detective` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.96 | - | 0/0/1343/0 | 0/71 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/charles-brockden-brown_wieland` | se | valid | yes | yes | yes | 35/35 | 3/3 | 6/6 | 35/35 | 9/9 | 0.89 | - | 0/0/1204/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/charles-dickens_barnaby-rudge` | se | valid | yes | yes | yes | 88/88 | 3/3 | 6/6 | 88/88 | 1/1 | 0.97 | - | 0/0/5262/0 | 0/67 | layout-hygiene, calibre-header-diff |
| `real/…oks/charles-dickens_the-mystery-of-edwin-drood` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 30/30 | 1/1 | 0.96 | - | 0/0/2842/0 | 0/81 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/charles-kingsley_hypatia` | se | valid | yes | yes | yes | 38/38 | 3/3 | 6/6 | 38/38 | 13/13 | 0.84 | - | 0/0/4012/0 | 0/83 | layout-hygiene, calibre-header-diff |
| `real/…arlotte-m-yonge_the-clever-woman-of-the-family` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.93 | - | 0/0/4495/0 | 0/83 | layout-hygiene, calibre-header-diff |
| `real/…s/charlotte-perkins-gilman_moving-the-mountain` | se | valid | yes | yes | yes | 18/18 | 3/3 | 6/6 | 18/18 | 1/1 | 0.96 | - | 0/0/1541/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/claude-mckay_banjo` | se | valid | yes | yes | yes | 34/34 | 3/3 | 6/6 | 34/34 | 1/1 | 0.89 | - | 0/0/2525/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/…ks/d-l-moody_the-way-to-god-and-how-to-find-it` | se | valid | yes | yes | yes | 16/16 | 3/3 | 6/6 | 16/16 | 5/5 | 0.85 | - | 0/0/588/0 | 0/78 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/david-hume_a-treatise-of-human-nature` | se | valid | yes | yes | yes | 113/113 | 3/3 | 6/6 | 113/113 | 187/187 | 0.73 | - | 0/0/2784/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dornford-yates_blind-corner` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.95 | - | 0/0/1781/0 | 0/76 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dornford-yates_perishable-goods` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.95 | - | 0/0/2298/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/…ayers_robert-eustace_the-documents-in-the-case` | se | valid | yes | yes | yes | 61/61 | 3/3 | 6/6 | 61/61 | 5/5 | 0.86 | - | 0/0/2500/0 | 0/90 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_deadlock` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.96 | - | 0/0/1201/0 | 0/66 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_interim` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.79 | - | 0/0/745/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_oberland` | se | valid | yes | yes | yes | 16/16 | 3/3 | 6/6 | 16/16 | 1/1 | 0.90 | - | 0/0/838/0 | 0/71 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/dorothy-m-richardson_revolving-lights` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 1/1 | 0.96 | - | 0/0/1046/0 | 0/74 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/dorothy-m-richardson_the-trap` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.89 | - | 0/0/973/0 | 0/76 | layout-hygiene, calibre-header-diff |
| `real/…ks/e-nesbit_beautiful-stories-from-shakespeare` | se | valid | yes | yes | yes | 27/27 | 3/3 | 6/6 | 27/27 | 1/1 | 0.90 | - | 0/0/1442/0 | 0/79 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/edgar-rice-burroughs_pirates-of-venus` | se | valid | yes | yes | yes | 18/18 | 3/3 | 6/6 | 18/18 | 1/1 | 0.96 | - | 0/0/1308/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/edgar-saltus_short-fiction` | se | valid | yes | yes | yes | 37/37 | 3/3 | 6/6 | 167/167 | 15/15 | 0.91 | - | 0/0/9966/0 | 0/110 | layout-hygiene, calibre-header-diff |
| `real/…andard-ebooks/edgar-saltus_the-perfume-of-eros` | se | valid | yes | yes | yes | 26/26 | 3/3 | 6/6 | 26/26 | 1/1 | 0.95 | - | 0/0/1469/0 | 0/66 | layout-hygiene, calibre-header-diff |
| `real/…-burke_reflections-on-the-revolution-in-france` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 123/123 | 0.50 | - | 0/0/890/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/…ebooks/ford-madox-ford_the-fifth-queen-crowned` | se | valid | yes | yes | yes | 32/32 | 3/3 | 6/6 | 32/32 | 1/1 | 0.95 | - | 0/0/1901/0 | 0/83 | layout-hygiene, calibre-header-diff |
| `real/…oks/franklin-w-dixon_the-great-airport-mystery` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.95 | - | 0/0/1885/0 | 0/66 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/george-eliot_romola` | se | valid | yes | yes | yes | 83/83 | 3/3 | 6/6 | 83/83 | 65/65 | 0.90 | - | 0/0/3508/0 | 0/74 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/george-macdonald_if-i-had-a-father` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 1/1 | 0.19 | - | 0/0/6294/0 | 0/83 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/george-macdonald_within-and-without` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 78/78 | 1/1 | 0.34 | - | 0/0/9445/0 | 0/109 | style-lost, layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-black-gang` | se | valid | yes | yes | yes | 22/22 | 3/3 | 6/6 | 22/22 | 1/1 | 0.95 | - | 0/0/1913/0 | 0/71 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-final-count` | se | valid | yes | yes | yes | 19/19 | 3/3 | 6/6 | 19/19 | 1/1 | 0.95 | - | 0/0/2280/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/h-c-mcneile_the-third-round` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.97 | - | 0/0/2026/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/h-g-wells_the-wheels-of-chance` | se | valid | yes | yes | yes | 33/33 | 4/4 | 8/8 | 74/74 | 3/3 | 0.70 | - | 0/0/1490/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/harry-harrison_short-fiction` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 1/1 | 0.89 | - | 0/0/1284/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/…oks/henry-seton-merriman_barlasch-of-the-guard` | se | valid | yes | yes | yes | 36/36 | 3/3 | 6/6 | 36/36 | 1/1 | 0.90 | - | 0/0/2470/0 | 0/81 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/henry-seton-merriman_the-sowers` | se | valid | yes | yes | yes | 48/48 | 3/3 | 6/6 | 48/48 | 1/1 | 0.96 | - | 0/0/3704/0 | 0/70 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/henry-van-dyke-jr_the-house-of-rimmon` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 17/17 | 3/3 | 0.32 | - | 0/0/4223/0 | 0/104 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/herbert-gorman_the-place-called-dagon` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 43/43 | 1/1 | 0.85 | - | 0/0/1485/0 | 0/71 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/hilaire-belloc_the-cruise-of-the-nona` | se | valid | yes | yes | yes | 8/8 | 3/3 | 6/6 | 8/8 | 1/1 | 0.61 | - | 0/0/1225/0 | 0/82 | layout-hygiene, calibre-header-diff |
| `real/…ooks/j-storer-clouston_the-man-from-the-clouds` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.92 | - | 0/0/2050/0 | 0/87 | layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/james-branch-cabell_the-line-of-love` | se | valid | yes | yes | yes | 20/20 | 3/3 | 6/6 | 20/20 | 5/5 | 0.68 | - | 0/0/2216/0 | 0/92 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/jane-c-loudon_the-mummy` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.94 | - | 0/0/3109/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/john-donne_poetry` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 219/219 | 1/1 | 0.28 | - | 0/0/12351/0 | 0/106 | style-lost, layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/john-gay_the-beggars-opera` | se | valid | yes | yes | yes | 13/13 | 71/71 | 142/142 | 23/23 | 69/69 | 0.31 | - | 0/0/4634/0 | 0/118 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…books/john-meade-falkner_the-lost-stradivarius` | se | valid | yes | yes | yes | 24/24 | 3/3 | 6/6 | 24/24 | 1/1 | 0.88 | - | 0/0/521/0 | 0/85 | layout-hygiene, calibre-header-diff |
| `real/…-ebooks/john-newton_william-cowper_olney-hymns` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 383/383 | 67/67 | 0.31 | - | 0/0/28663/0 | 0/80 | style-lost, layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_chance` | se | valid | yes | yes | yes | 23/23 | 3/3 | 6/6 | 23/23 | 1/1 | 0.95 | - | 0/0/2137/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/…h-conrad_ford-madox-ford_the-nature-of-a-crime` | se | valid | yes | yes | yes | 15/15 | 3/3 | 6/6 | 15/15 | 1/1 | 0.83 | - | 0/0/279/0 | 0/68 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_suspense` | se | valid | yes | yes | yes | 25/25 | 3/3 | 6/6 | 25/25 | 1/1 | 0.97 | - | 0/0/1508/0 | 0/68 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-arrow-of-gold` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.96 | - | 0/0/1873/0 | 0/84 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-rescue` | se | valid | yes | yes | yes | 55/55 | 3/3 | 6/6 | 55/55 | 1/1 | 0.96 | - | 0/0/2923/0 | 0/85 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/joseph-conrad_the-rover` | se | valid | yes | yes | yes | 23/23 | 3/3 | 6/6 | 23/23 | 1/1 | 0.96 | - | 0/0/1483/0 | 0/84 | layout-hygiene, calibre-header-diff |
| `real/…s/joshua-slocum_sailing-alone-around-the-world` | se | valid | yes | yes | yes | 30/30 | 14/14 | 28/28 | 30/30 | 28/28 | 0.85 | - | 0/0/963/0 | 0/92 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/kahlil-gibran_jesus-the-son-of-man` | se | valid | yes | yes | yes | 83/83 | 3/3 | 6/6 | 83/83 | 1/1 | 0.76 | - | 0/0/2324/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/…arine-a-carl_with-the-empress-dowager-of-china` | se | valid | yes | yes | yes | 44/44 | 24/24 | 27/27 | 44/44 | 40/40 | 0.74 | - | 0/0/1204/0 | 0/85 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/maria-lowell_poetry` | se | valid | yes | yes | yes | 6/6 | 3/3 | 6/6 | 25/25 | 3/3 | 0.33 | - | 0/0/1149/0 | 0/77 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…s/marie-belloc-lowndes_the-chink-in-the-armour` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 31/31 | 1/1 | 0.97 | - | 0/0/2718/0 | 0/76 | layout-hygiene, calibre-header-diff |
| `real/…-ebooks/marmaduke-pickthall_said-the-fisherman` | se | valid | yes | yes | yes | 55/55 | 3/3 | 6/6 | 55/55 | 9/9 | 0.87 | - | 0/0/2211/0 | 0/77 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/mary-augusta-ward_lady-roses-daughter` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.96 | - | 0/0/3827/0 | 0/73 | layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/mary-p-hamlin_george-arliss_hamilton` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 12/12 | 1/1 | 0.15 | - | 0/0/6376/0 | 0/99 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/mourning-dove_cogewea-the-half-blood` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 119/119 | 0.76 | - | 0/0/2616/0 | 0/100 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/noel-coward_hay-fever` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 1/1 | 0.15 | - | 0/0/6955/0 | 0/100 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…ndard-ebooks/noel-loomis_short-science-fiction` | se | valid | yes | yes | yes | 13/13 | 3/3 | 6/6 | 13/13 | 1/1 | 0.91 | - | 0/0/1413/0 | 0/71 | layout-hygiene, calibre-header-diff |
| `real/…andard-ebooks/norman-angell_the-great-illusion` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 31/31 | 267/267 | 0.61 | - | 0/0/1890/0 | 0/69 | layout-hygiene, calibre-header-diff |
| `real/…ndard-ebooks/olaf-stapledon_last-and-first-men` | se | valid | yes | yes | yes | 24/24 | 7/7 | 14/14 | 80/80 | 5/5 | 0.72 | - | 0/0/1339/0 | 0/70 | layout-hygiene, calibre-header-diff |
| `real/…d-ebooks/p-g-wodehouse_the-adventures-of-sally` | se | valid | yes | yes | yes | 22/22 | 3/3 | 6/6 | 59/59 | 1/1 | 0.86 | - | 0/0/2704/0 | 0/75 | layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/pauline-e-hopkins_contending-forces` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.79 | - | 0/0/2086/0 | 0/112 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/pauline-e-hopkins_of-one-blood` | se | valid | yes | yes | yes | 28/28 | 3/3 | 6/6 | 28/28 | 1/1 | 0.83 | - | 0/0/1448/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/ring-lardner_fred-gross-stories` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.59 | - | 0/0/1295/0 | 0/76 | layout-hygiene, calibre-header-diff |
| `real/…ebooks/ring-lardner_george-s-kaufman_june-moon` | se | valid | yes | yes | yes | 11/11 | 3/3 | 6/6 | 11/11 | 1/1 | 0.18 | - | 0/0/6575/0 | 0/98 | style-lost, layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/ring-lardner_gullibles-travels` | se | valid | yes | yes | yes | 12/12 | 3/3 | 6/6 | 28/28 | 1/1 | 0.94 | - | 0/0/2174/0 | 0/68 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/ring-lardner_short-fiction` | se | valid | yes | yes | yes | 80/80 | 3/3 | 6/6 | 203/203 | 115/115 | 0.87 | - | 0/0/15644/0 | 0/86 | layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/robert-hugh-benson_the-necromancers` | se | valid | yes | yes | yes | 25/25 | 3/3 | 6/6 | 68/68 | 1/1 | 0.81 | - | 0/0/2738/0 | 0/70 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/robert-louis-stevenson_poetry` | se | valid | yes | yes | yes | 7/7 | 13/13 | 26/26 | 385/385 | 99/99 | 0.30 | - | 0/0/13628/0 | 0/93 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/rudolph-fisher_the-walls-of-jericho` | se | valid | yes | yes | yes | 40/40 | 3/3 | 6/6 | 40/40 | 57/57 | 0.86 | - | 0/0/2533/0 | 0/88 | layout-hygiene, calibre-header-diff |
| `real/…ard-ebooks/rudyard-kipling_captains-courageous` | se | valid | yes | yes | yes | 17/17 | 3/3 | 6/6 | 17/17 | 1/1 | 0.88 | - | 0/0/1659/0 | 0/93 | layout-hygiene, calibre-header-diff |
| `real/…leridge_robert-southey_the-fall-of-robespierre` | se | valid | yes | yes | yes | 10/10 | 3/3 | 6/6 | 10/10 | 7/7 | 0.35 | - | 0/0/2000/0 | 0/93 | style-lost, layout-hygiene, calibre-header-diff |
| `real/…egfried-sassoon_memoirs-of-an-infantry-officer` | se | valid | yes | yes | yes | 14/14 | 3/3 | 6/6 | 50/50 | 1/1 | 0.61 | - | 0/0/764/0 | 0/72 | layout-hygiene, calibre-header-diff |
| `real/…e-roosevelt_a-book-lovers-holidays-in-the-open` | se | valid | yes | yes | yes | 23/23 | 5/5 | 9/9 | 23/23 | 10/10 | 0.73 | - | 0/0/1054/0 | 0/113 | layout-hygiene, calibre-header-diff |
| `real/…s/w-e-b-du-bois_the-quest-of-the-silver-fleece` | se | valid | yes | yes | yes | 45/45 | 3/3 | 6/6 | 45/45 | 1/1 | 0.96 | - | 0/0/3948/0 | 0/84 | layout-hygiene, calibre-header-diff |
| `real/…/w-h-davies_the-autobiography-of-a-super-tramp` | se | valid | yes | yes | yes | 40/40 | 3/3 | 6/6 | 40/40 | 1/1 | 0.81 | - | 0/0/686/0 | 0/67 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/walter-white_flight` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.88 | - | 0/0/1575/0 | 0/79 | layout-hygiene, calibre-header-diff |
| `real/…dard-ebooks/walter-white_the-fire-in-the-flint` | se | valid | yes | yes | yes | 30/30 | 3/3 | 6/6 | 30/30 | 1/1 | 0.95 | - | 0/0/1190/0 | 0/83 | layout-hygiene, calibre-header-diff |
| `real/standard-ebooks/wilkie-collins_basil` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 42/42 | 3/3 | 0.90 | - | 0/0/1801/0 | 0/79 | layout-hygiene, calibre-header-diff |
| `real/…ndard-ebooks/willa-cather_the-professors-house` | se | valid | yes | yes | yes | 39/39 | 3/3 | 6/6 | 39/39 | 1/1 | 0.92 | - | 0/0/1153/0 | 0/82 | layout-hygiene, calibre-header-diff |
| `real/…rd-ebooks/winnifred-eaton-reeve_his-royal-nibs` | se | valid | yes | yes | yes | 33/33 | 3/3 | 6/6 | 33/33 | 1/1 | 0.95 | - | 0/0/1340/0 | 0/80 | layout-hygiene, calibre-header-diff |
| `real/…-ebooks/yung-wing_my-life-in-china-and-america` | se | valid | yes | yes | yes | 31/31 | 3/3 | 6/6 | 36/36 | 3/3 | 0.83 | - | 0/0/672/0 | 0/77 | layout-hygiene, calibre-header-diff |

