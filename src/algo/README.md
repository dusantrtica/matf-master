# Benchmark: CP-SAT vs MIP/SCIP za rasporedivanje nastave

Ovaj dokument sumira rezultate benchmark-a koji uporeduje dva pristupa
resavanja problema nedeljnog rasporeda nastave: **CP-SAT** (Constraint
Programming, OR-Tools) i **MIP/SCIP** (Mixed Integer Programming preko
OR-Tools `pywraplp` SCIP backend-a).

Cilj poredjenja je: **da li solver moze da pronadje bilo koji validan
raspored koji zadovoljava sva tvrda ogranicenja?**

---

## 1. Opis problema

Treba napraviti **nedeljni raspored predavanja** za fakultet, gde se sesije
(predavanja i vezbe) dodeljuju trojkama `(dan, sat, ucionica)`.

### Ulazni podaci

Ulaz je definisan u [model.py](model.py) klasama:

- `Settings` - radni dani (`workingDays`), `start_hour`, `end_hour`, radno vreme fakulteta.
- `Classroom` - ucionica sa flag-om `has_computers` i kapacitetom.
- `Course` sa `Quota(theory, practice)` - koliko teorijskih i koliko prakticnih
  casova nedeljno smer treba da odslusa za taj predmet.
- `StudentsEnrolled` - koliko studenata je upisano u dati smer/semestar.

Podaci dolaze iz [input_full_1_semester.json](input_full_1_semester.json)
6 odseka (5 modula Matematike + Informatika) sa 35 ucionica na 3 lokacije.
Razmatramo prvi semestar za sve četiri godine studija, dakle semestri: 1, 3, 5, 7

### Generisanje sesija

Svaki upisani broj studenata se deli u grupe od po `GROUP_SIZE = 30`
(videti [data.py](data.py), funkcija `split_students_into_groups`). Za svaku
grupu i svaki predmet generise se po `quota.theory` teorijskih i
`quota.practice` prakticnih sesija (`generate_sessions` u [data.py](data.py)).
Jedna sesija = jedan cas u rasporedu.

### Tvrda ogranicenja (hard constraints)

Oba solvera namecu identican skup tvrdih ogranicenja:

1. **Učionica zauzeta jednom u datom satu.** Nikoje dve sesije ne dele isti
   `(dan, sat, ucionica)`.
2. **Grupa ne može biti na dva mesta odjednom.** Nijedna grupa ne sme imati
   dve sesije u istom `(dan, sat)`.
3. **Računarske ucionice za predmete koji ih zahtevaju.** Sesija sa
   `needs_computers = true` moze zavrsiti samo u ucionici sa
   `has_computers = true`.

### Rezim: feasibility-only

Solveri ne minimizuju nijednu funkciju cilja. Traze se **bilo koji raspored**
koji zadovoljava gore navedena tvrda ograničejna, dakle da se predmeti i grupe ne sudaraju.

---

## 2. Pristupi resavanju

### CP-SAT (Constraint Programming)

Definicija u [cp_solver.py](cp_solver.py), klasa `SimpleCPSolver`.

Po sesiji `s` se kreira **5 celobrojnih promenljivih**:

- `day_var[s]`        u `[0, D-1]`
- `slot_var[s]`       u `[0, H-1]`
- `room_var[s]`       u `[0, R-1]`
- `flat_time_var[s] = day_var[s] * H + slot_var[s]` (linearizacija (dan, sat))
- `room_time_var[s] = room_var[s] * D*H + flat_time_var[s]` (linearizacija (dan, sat, ucionica))

Tvrda ogranicenja su zatim izrazena kao dva globalna `AllDifferent`:

- `AllDifferent(room_time_var)` -- sve sesije imaju jedinstvenu trojku.
- Po grupi: `AllDifferent(flat_time_var[s] for s in group)` -- grupa nema dve
  sesije u istom `(dan, sat)`.

Sesije sa `needs_computers` dobijaju `AddAllowedAssignments` na `room_var`
sa listom dozvoljenih učionica, koje imaju računare.

Velicina modela: **O(S)** promenljivih (5 po sesiji).

### MIP/SCIP (Mixed Integer Programming)

Definicija u [mip_solver.py](mip_solver.py), klasa `SimpleMIPSolver`. Solver
je SCIP preko `pywraplp.Solver.CreateSolver("SCIP")`.

Po sesiji `s` se kreira **binarna promenljiva `x[s, d, h, r]`** za svaku
dozvoljenu trojku `(d, h, r)` -- jedinica znaci "sesija s je u danu d, satu
h, ucionici r".

Ogranicenja su klasicne linearne nejednakosti:

- `sum_{d,h,r} x[s,d,h,r] == 1` za svako `s` (svaka sesija rasporedjena tacno jednom).
- `sum_s x[s,d,h,r] <= 1` za svako `(d,h,r)` (ucionica nije dvostruko zauzeta).
- `sum_{s in g, r} x[s,d,h,r] <= 1` po grupi i `(d,h)`.

Velicina modela: **O(S * D * H * R)** binarnih promenljivih.

---

## 3. Šta je mereno:

| Polje | Sta predstavlja | Kako se meri |
|---|---|---|
| `num_sessions` | Broj generisanih sesija | `len(solver.sessions)` |
| `num_variables` | Broj promenljivih u modelu | `model.Proto().variables` (CP) / `solver.NumVariables()` (MIP) |
| `num_constraints` | Broj ograničenja u modelu | `model.Proto().constraints` (CP) / `solver.NumConstraints()` (MIP) |
| `construction_time_s` | Vreme izgradnje modela | `time.perf_counter` razlika oko konstruktora |
| `solve_time_s` | Čisto vreme resavanja | `time.perf_counter` razlika oko `solver.Solve(...)` |
| `total_time_s` | Konstrukcija + rešavanje | zbir gornja dva |
| `model_memory_kb` | Memorija alocirana tokom konstrukcije modela | `tracemalloc` snapshot razlika |
| `peak_memory_kb` | Maksimalan RSS procesa | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| `status` | Status koji solver vraca | `FEASIBLE`, `INFEASIBLE`, `NOT_SOLVED`, ... |
| `solution_valid` | Da li resenje stvarno postuje sve hard constraints | `validate_solution(...)` u `benchmark.py` |

**Validacija resenja** je nezavisna od solvera: `validate_solution` ponovo
proverava da nikoje dve sesije ne dele `(dan, sat, ucionica)`, da nijedna
grupa nema dve sesije u istom `(dan, sat)`, i da svaka sesija sa
`needs_computers` jeste u ucionici sa racunarima.

### Skale (podskupovi iz `input_full_1_semester.json`)

| Skala  | Godine | Semestri | Lokacije                  | Ucionice | PC ucionice | Sesije | Limit |
|--------|--------|----------|---------------------------|----------|-------------|--------|-------|
| MATF-S | 1.     | 1        | Studentski trg            | 18       | 4           | 240    | 60s   |
| MATF-M | 1-2.   | 1, 3     | Studentski trg + Jagiceva | 22       | 8           | 484    | 120s  |
| MATF-L | 1-4.   | 1,3,5,7  | sve                       | 35       | 8           | 937    | 300s  |

---

## 4. Masina i okruzenje

Sva merenja u nastavku su izvrsena na sledecem hardveru i softveru:

| Stavka | Vrednost |
|---|---|
| CPU | Apple M4 (ARM64) |
| Broj jezgara | 10 |
| RAM | 24 GB |
| OS | macOS 15.6.1 (build 24G90) |
| Python | 3.11 (preko Bazel toolchain-a, vidi [MODULE.bazel](../../MODULE.bazel) - `python_version="3.11"`) |
| Build sistem | Bazel sa `rules_python` 1.4.1 |
| CP solver | OR-Tools CP-SAT |
| MIP solver | OR-Tools `pywraplp` sa SCIP backend-om |
| Komanda za pokretanje | `python -m src.algo.benchmark` |

---

## 5. Rezultati

### 5.1 MATF-S (240 sesija, 18 ucionica, 5 dana x 12 sati, limit 60s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 240 | 240 |
| Broj promenljivih | 1,200 | 203,760 |
| Broj ogranicenja | 557 | 1,970 |
| Vreme konstrukcije | **0.0109 s** | 5.5856 s |
| Vreme resavanja | **0.0672 s** | 3.2280 s |
| Ukupno vreme | **0.08 s** | 8.81 s |
| Memorija modela | 232.5 KB | 59,628.0 KB (~58 MB) |
| Maksimalan RSS | 159,376 KB (~156 MB) | 1,745,328 KB (~1.66 GB) |
| Status | **FEASIBLE** | **FEASIBLE** |
| Validnost resenja | PASS | PASS |

**Komentar:** oba solvera nalaze validan raspored. CP-SAT zavrsava za
**0.08 s** (110x brze od MIP-a). Razlika u broju promenljivih: **170x**.

### 5.2 MATF-M (484 sesije, 22 ucionice, 5 dana x 12 sati, limit 120s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 484 | 484 |
| Broj promenljivih | 2,420 | 522,120 |
| Broj ogranicenja | 1,127 | 3,039 |
| Vreme konstrukcije | **0.0187 s** | 14.0075 s |
| Vreme resavanja | **0.5304 s** | 11.1279 s |
| Ukupno vreme | **0.55 s** | 25.14 s |
| Memorija modela | 399.8 KB | 149,847.3 KB (~146 MB) |
| Maksimalan RSS | 1,746,208 KB (~1.67 GB) | 3,911,360 KB (~3.73 GB) |
| Status | **FEASIBLE** | **FEASIBLE** |
| Validnost resenja | PASS | PASS |

**Komentar:** oba solvera ponovo nalaze validan raspored. CP-SAT: **0.55 s**,
MIP: **25.14 s** (46x brze). MIP-u treba 14 s samo za konstrukciju modela
(kreiranje 522K binarnih promenljivih).

### 5.3 MATF-L (937 sesija, 35 ucionica, 5 dana x 12 sati, limit 300s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 937 | 937 |
| Broj promenljivih | 4,685 | 1,433,100 |
| Broj ogranicenja | 2,242 | 5,442 |
| Vreme konstrukcije | **0.0386 s** | 39.8268 s |
| Vreme resavanja | **5.3573 s** | 302.0865 s |
| Ukupno vreme | **5.40 s** | 341.91 s |
| Memorija modela | 744.7 KB | 419,614.7 KB (~410 MB) |
| Maksimalan RSS | 4,089,392 KB (~3.90 GB) | 7,180,896 KB (~6.85 GB) |
| Status | **FEASIBLE** | **NOT_SOLVED** |
| Validnost resenja | **PASS** | N/A |

**Komentar:** CP-SAT pronadje validan raspored za **5.40 s**.
MIP/SCIP ne uspe da vrati nijedno
resenje u 5-minutnom limitu. Gubi ~40 s na konstrukciju 1.43M binarnih
promenljivih, a preostalo vreme (~300 s) nije dovoljno da SCIP zavrsi
LP relaxation i pronadje celobrojno resenje za model te velicine.
Razlika u broju promenljivih: **306x**.

---

## 6. Zbirna tabela

| Skala  | Sesije | CP vars | MIP vars | CP vreme (s) | MIP vreme (s) | CP RSS (MB) | MIP RSS (MB) | CP status | MIP status |
|--------|-------:|--------:|---------:|-------------:|---------------:|------------:|-------------:|-----------|------------|
| MATF-S | 240    | 1,200   | 203,760  | 0.08         | 8.81           | 156         | 1,664        | FEASIBLE  | FEASIBLE   |
| MATF-M | 484    | 2,420   | 522,120  | 0.55         | 25.14          | 1,670       | 3,730        | FEASIBLE  | FEASIBLE   |
| MATF-L | 937    | 4,685   | 1,433,100| 5.40         | 341.91         | 3,900       | 6,850        | FEASIBLE  | NOT_SOLVED |

---

## 7. Analiza i nalazi

### 7.1 Velicina modela

CP-SAT model raste **linearno** sa brojem sesija: `5 * S` celobrojnih
promenljivih. MIP/SCIP model raste **multiplikativno**: `S * D * H * R`
binarnih promenljivih.

| Skala  | CP vars | MIP vars | Faktor |
|--------|--------:|---------:|-------:|
| MATF-S | 1,200   | 203,760  | 170x   |
| MATF-M | 2,420   | 522,120  | 216x   |
| MATF-L | 4,685   | 1,433,100| 306x   |

Faktor raste sa svakom dodatnom dimenzijom jer je MIP-ov rast multiplikativan
(`S * D * H * R`) dok CP ostaje linearan (`5 * S`).

### 7.2 Vreme resavanja (feasibility)

| Skala  | CP vreme | MIP vreme | Odnos | CP status | MIP status |
|--------|----------|-----------|-------|-----------|------------|
| MATF-S | 0.08 s   | 8.81 s    | 110x  | FEASIBLE  | FEASIBLE   |
| MATF-M | 0.55 s   | 25.14 s   | 46x   | FEASIBLE  | FEASIBLE   |
| MATF-L | 5.40 s   | 341.91 s  | 63x   | FEASIBLE  | NOT_SOLVED |

Kljucni nalaz: **CP-SAT je 46-110x brzi** na skalama gde oba solvera uspeju.
Na MATF-L skali CP zavrsava za 5.4 s dok MIP ne vraca nijedno resenje
ni nakon 5 minuta.

### 7.3 Memorija

| Skala  | CP model (KB) | MIP model (KB) | Faktor |
|--------|---------------|----------------|--------|
| MATF-S | 233           | 59,628         | 256x   |
| MATF-M | 400           | 149,847        | 375x   |
| MATF-L | 745           | 419,615        | 563x   |

CP modeli zauzimaju manje od 1 MB u svim skalama.
Maksimalan RSS na MATF-L: CP ~3.9 GB vs MIP ~6.9 GB.

### 7.4 Validnost

Sva resenja koja su solveri prijavili **prolaze** post-hoc `validate_solution`
proveru. Nije bilo lazno-pozitivnih izlaza ni kod jednog solvera, sto znaci
da su oba modela korektno postavljena.

Pojedinacni solveri (postojeci Bazel target-i u [BUILD.bazel](BUILD.bazel)):

```bash
bazel run //src/algo:run_cp_solver
bazel run //src/algo:run_mip_solver
```

Testovi:

```bash
bazel test //src/algo:test_cp_solver
bazel test //src/algo:test_mip_solver
bazel test //src/algo:test_data
```

---

## 9. Zakljucak

Na osnovu merenja iznad, **CP-SAT je znatno performantiji i pogodniji** za nas problem
nedeljnog rasporeda nastave.

1. **Velicina modela** -- linearna umesto multiplikativne (**170-306x**
   manje promenljivih).
2. **Vreme resavanja** -- **46-110x brze** na skalama gde oba solvera
   uspeju; na MATF-L (937 sesija) CP zavrsi za 5.4 s, MIP ne vrati
   nijedno resenje ni za 5 minuta.
3. **Memorija** -- **256-563x** manje za model; ~1.8x manje RSS.
4. **Skalabilnost** -- CP-SAT uspesno resava problem sa 937 sesija i 35
   ucionica za 5.4 s, sto omogucuje interaktivnu upotrebu.
