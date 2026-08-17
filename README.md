# Raspoređivanje nastave (MATF master rad)

Aplikacija koja na osnovu ulaznog JSON fajla (predmeti, smerovi, učionice,
broj upisanih studenata, nastavno osoblje) pravi **nedeljni raspored časova**
fakulteta. Problem je rešen kroz dve paradigme:

- **Constraint Programming (CP-SAT, OR-Tools)** — `src/algo/cp_solver.py`
- **Mixed Integer Programming (SCIP preko OR-Tools `pywraplp`)** — `src/algo/mip_solver.py`

Nad oba pristupa je urađen detaljan benchmark (vreme, memorija, veličina
modela, skalabilnost). CP-SAT se pokazao kao ubedljivo bolji pristup, pa se
sistem dalje nadograđuje na CP strani dodavanjem novih pravila.

Kompletni rezultati benchmark-a, opis modela i analiza nalaze se u
**[src/algo/README.md](src/algo/README.md)**.

## Struktura repozitorijuma

- `src/algo/` — solveri (CP i MIP), učitavanje podataka (`data.py`,
  `model.py`), runneri, benchmark, izveštaji (`report.py`), ulazni JSON
  fajlovi i testovi.
- `src/rules/` — plugin sistem pravila rasporeda. Svako pravilo nasleđuje
  `SchedulingRule` (`base.py`) i može biti **hard** (`penalty == 0`, mora
  biti ispunjeno) ili **soft** (`penalty > 0`, solver minimizuje broj
  prekršaja uz datu cenu).
  - `src/rules/general/` — pravila za grupe, sesije i studente.
  - `src/rules/staff/` — pravila za nastavno osoblje.
- `notebooks/` — Jupyter sveske za interaktivno igranje sa solverom.
- `docs/` — tekst master rada.
- `out/` — generisani Excel rasporedi.

## Pravila rasporeda

Pravila se uključuju i konfigurišu kroz sekciju `rules` u ulaznim JSON
fajlovima (npr. `src/algo/input_full_1_semester.json` i
`src/algo/staff_2_semester.json`), bez izmene koda:

```json
"staffMaxWorkingDays": {
  "enabled": true,
  "penalty": 3,
  "params": { "maxDays": 4 }
}
```

### Osnovna hard ograničenja (uvek aktivna, u `cp_solver.py`)

1. Nikoje dve sesije ne dele istu trojku `(dan, sat, učionica)`.
2. Grupa (tok) ne može imati dva časa u istom trenutku.
3. Sesija koja zahteva računare ide samo u učionicu sa računarima;
   kapacitet učionice se poštuje kada su grupe eksplicitno zadate.
   Zahtev se zadaje odvojeno za predavanja i vežbe
   (`"needsComputers": {"theory": false, "practice": true}`), pa
   predavanja iz predmeta čije vežbe traže računare mogu u bilo koju
   učionicu.
4. Nastavnik ne može držati dve sesije u istom trenutku.

### Pravila za grupe, sesije i studente (`src/rules/general/`)

| Pravilo (ključ u JSON-u) | Opis |
|---|---|
| `joinSameClasses` | Časovi istog predmeta, grupe i tipa se spajaju u blokove (dvočas, tročas; kvota 4 se deli na dva dvočasa) — isti dan, ista učionica, sat za satom. |
| `noGapsInSchedule` | Grupa nema procepe u danu (slobodan sat između dva zauzeta sata). Kao hard zabranjuje sve procepe, kao soft ih minimizuje. |
| `singleLocationInDayForGroup` | Grupa u toku jednog dana ne menja lokaciju (Trg, Sv. Nikole, Jagićeva) — svi časovi tog dana su na istoj lokaciji. |

### Pravila za nastavno osoblje (`src/rules/staff/`)

| Pravilo (ključ u JSON-u) | Opis |
|---|---|
| `staffMaxWorkingDays` | Nastavnik drži nastavu najviše `maxDays` dana nedeljno (podrazumevano 4); pojedinačni nastavnik može imati svoj limit preko polja `maxWorkingDays`. |
| `staffMaxGapHoursPerWeek` | Ukupan broj procepa (slobodnih sati između časova) nastavnika u toku cele nedelje je najviše `maxGapHours` (podrazumevano 1). |
| `staffSingleLocationInDay` | Nastavnik u toku jednog dana ne menja lokaciju — svi njegovi časovi tog dana su na istoj lokaciji. |

Nastavnici i njihove dodele predmetima zadaju se u posebnom staff JSON
fajlu (npr. `src/algo/staff_2_semester.json`) i prosleđuju solveru opciono.

## Pokretanje

Projekat se gradi Bazel-om (Python 3.11 preko Bazel toolchain-a).

CP solver (podrazumevani ulaz i limit su definisani u `BUILD.bazel`):

```bash
bazel run //src/algo:run_cp_solver
```

CP solver sa sopstvenim argumentima:

```bash
bazel run //src/algo:run_cp_solver -- \
  --input input_full_2_semester.json \
  --staff staff_2_semester.json \
  --time-limit 600 \
  --verbose
```

Raspored se izvozi u Excel u `out/schedule.xlsx` (putanja se može
promeniti promenljivom okruženja `SCHEDULE_OUTPUT`).

MIP solver:

```bash
bazel run //src/algo:run_mip_solver
```

Benchmark CP vs MIP:

```bash
bazel run //src/algo:benchmark
```

Interaktivni rad (JupyterLab, pravi lokalni `.venv`):

```bash
./notebook.sh
```

## Testovi

Svi testovi odjednom:

```bash
bazel test //src/algo:all
```

Pojedinačni testovi:

```bash
bazel test //src/algo:test_data
bazel test //src/algo:test_cp_solver
bazel test //src/algo:test_mip_solver
bazel test //src/algo:test_no_gaps_in_schedule
bazel test //src/algo:test_staff_rules
```
