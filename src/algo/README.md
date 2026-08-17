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
  casova nedeljno smer treba da odslusa za taj predmet, i sa
  `ComputerNeed(theory, practice)` - da li racunari trebaju predavanjima,
  vezbama ili i jednima i drugima.
- `StudentsEnrolled` - koliko studenata je upisano u dati smer/semestar.

Podaci dolaze iz [input_full_1_semester.json](input_full_1_semester.json)
6 odseka (5 modula Matematike + Informatika) sa 29 ucionica na 3 lokacije,
od kojih 8 ima racunare.
Razmatramo prvi semestar za sve četiri godine studija, dakle semestri: 1, 3, 5, 7

### Generisanje sesija

Svaki upisani broj studenata se deli u grupe od po `GROUP_SIZE = 30`
(videti [data.py](data.py), funkcija `split_students_into_groups`). Za svaku
grupu i svaki predmet generise se po `quota.theory` teorijskih i
`quota.practice` prakticnih sesija (`generate_sessions` u [data.py](data.py)).
Jedna sesija = jedan cas u rasporedu.

Predavanja i vezbe su **nezavisne jedinice rasporedjivanja**: broj casova,
nastavnik, kohorta slusalaca, termin, ucionica i zahtev za racunarima
odredjuju se odvojeno po tipu. Zbog toga sesija ne nasledjuje zahtev celog
predmeta nego samo zahtev svog tipa
(`course.needs_computers_for(session_type)`), sto odgovara praksi da
predavanje iz programiranja ide u amfiteatar a vezbe u racunarsku ucionicu.

### Tvrda ogranicenja (hard constraints)

Oba solvera namecu identican skup tvrdih ogranicenja:

1. **Učionica zauzeta jednom u datom satu.** Nikoje dve sesije ne dele isti
   `(dan, sat, ucionica)`.
2. **Grupa ne može biti na dva mesta odjednom.** Nijedna grupa ne sme imati
   dve sesije u istom `(dan, sat)`.
3. **Računarske ucionice za casove koji ih zahtevaju.** Sesija sa
   `needs_computers = true` moze zavrsiti samo u ucionici sa
   `has_computers = true`. Zahtev je vezan za tip casa, ne za predmet, pa
   predavanja iz predmeta cije vezbe traze racunare i dalje mogu u bilo koju
   ucionicu.

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
sa listom dozvoljenih učionica, koje imaju računare. Kako zahtev zavisi od
tipa casa, ovo ogranicenje se dodaje samo delu sesija (na MATF-L skali 116 od
762), pa je ukupan broj ogranicenja manji nego kad bi ga nasledjivao ceo
predmet.

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

`peak_memory_kb` je maksimalan RSS **celog procesa** i monotono raste kroz
skale, pa se ne moze citati kao potrosnja pojedinacne skale; za poredjenje
modela koristiti `model_memory_kb`.

### Skale (podskupovi iz `input_full_1_semester.json`)

| Skala  | Godine | Semestri | Lokacije                  | Ucionice | PC ucionice | Sesije | Sesije sa PC | Limit |
|--------|--------|----------|---------------------------|----------|-------------|--------|--------------|-------|
| MATF-S | 1.     | 1        | Studentski trg            | 12       | 4           | 192    | 26           | 600s  |
| MATF-M | 1-2.   | 1, 3     | Studentski trg + Jagiceva | 16       | 8           | 410    | 52           | 600s  |
| MATF-L | 1-4.   | 1,3,5,7  | sve                       | 29       | 8           | 762    | 116          | 600s  |

---

## 4. Masina i okruzenje

Sva merenja u nastavku su izvrsena na sledecem hardveru i softveru:

| Stavka | Vrednost |
|---|---|
| CPU | Apple M4 (ARM64) |
| Broj jezgara | 10 |
| RAM | 24 GB |
| OS | macOS 26.5.2 (build 25F84) |
| Python | 3.11 (preko Bazel toolchain-a, vidi [MODULE.bazel](../../MODULE.bazel) - `python_version="3.11"`) |
| Build sistem | Bazel sa `rules_python` 1.4.1 |
| CP solver | OR-Tools CP-SAT |
| MIP solver | OR-Tools `pywraplp` sa SCIP backend-om |
| Komanda za pokretanje | `bazel run //src/algo:benchmark -- --json report.json` |

---

## 5. Rezultati

### 5.1 MATF-S (192 sesije, 12 ucionica, 5 dana x 12 sati, limit 600s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 192 | 192 |
| Broj promenljivih | 1,152 | 125,760 |
| Broj ogranicenja | 611 | 1,392 |
| Vreme konstrukcije | **0.0139 s** | 2.0007 s |
| Vreme resavanja | **0.0212 s** | 1.3843 s |
| Ukupno vreme | **0.04 s** | 3.39 s |
| Memorija modela | 217.4 KB | 29,928.1 KB (~29 MB) |
| Status | **FEASIBLE** | **FEASIBLE** |
| Validnost resenja | PASS | PASS |

**Komentar:** oba solvera nalaze validan raspored. CP-SAT zavrsava za
**0.04 s** (96x brze od MIP-a). Razlika u broju promenljivih: **109x**.

### 5.2 MATF-M (410 sesija, 16 ucionica, 5 dana x 12 sati, limit 600s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 410 | 410 |
| Broj promenljivih | 2,460 | 368,640 |
| Broj ogranicenja | 1,299 | 2,330 |
| Vreme konstrukcije | **0.0293 s** | 5.9531 s |
| Vreme resavanja | **0.0805 s** | 6.0936 s |
| Ukupno vreme | **0.11 s** | 12.05 s |
| Memorija modela | 412.0 KB | 83,150.8 KB (~81 MB) |
| Status | **FEASIBLE** | **FEASIBLE** |
| Validnost resenja | PASS | PASS |

**Komentar:** oba solvera ponovo nalaze validan raspored. CP-SAT: **0.11 s**,
MIP: **12.05 s** (110x brze). MIP-u treba 6 s samo za konstrukciju modela
(kreiranje 369K binarnih promenljivih).

### 5.3 MATF-L (762 sesije, 29 ucionica, 5 dana x 12 sati, limit 600s)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 762 | 762 |
| Broj promenljivih | 4,572 | 1,179,720 |
| Broj ogranicenja | 2,433 | 4,302 |
| Vreme konstrukcije | **0.0579 s** | 22.7477 s |
| Vreme resavanja | **0.8377 s** | 25.3872 s |
| Ukupno vreme | **0.90 s** | 48.13 s |
| Memorija modela | 747.2 KB | 270,175.6 KB (~264 MB) |
| Status | **FEASIBLE** | **FEASIBLE** |
| Validnost resenja | **PASS** | **PASS** |

**Komentar:** CP-SAT pronadje validan raspored za **0.90 s**, MIP/SCIP za
**48.13 s** (54x sporije), od cega ~23 s odlazi samo na konstrukciju 1.18M
binarnih promenljivih. Razlika u broju promenljivih: **258x**.

---

## 6. Zbirna tabela

| Skala  | Sesije | CP vars | MIP vars  | CP vreme (s) | MIP vreme (s) | CP model (MB) | MIP model (MB) | CP status | MIP status |
|--------|-------:|--------:|----------:|-------------:|--------------:|--------------:|---------------:|-----------|------------|
| MATF-S | 192    | 1,152   | 125,760   | 0.04         | 3.39          | 0.21          | 29.2           | FEASIBLE  | FEASIBLE   |
| MATF-M | 410    | 2,460   | 368,640   | 0.11         | 12.05         | 0.40          | 81.2           | FEASIBLE  | FEASIBLE   |
| MATF-L | 762    | 4,572   | 1,179,720 | 0.90         | 48.13         | 0.73          | 263.8          | FEASIBLE  | FEASIBLE   |

---

## 7. Analiza i nalazi

### 7.1 Velicina modela

CP-SAT model raste **linearno** sa brojem sesija: `5 * S` celobrojnih
promenljivih. MIP/SCIP model raste **multiplikativno**: `S * D * H * R`
binarnih promenljivih.

| Skala  | CP vars | MIP vars  | Faktor |
|--------|--------:|----------:|-------:|
| MATF-S | 1,152   | 125,760   | 109x   |
| MATF-M | 2,460   | 368,640   | 150x   |
| MATF-L | 4,572   | 1,179,720 | 258x   |

Faktor raste sa svakom dodatnom dimenzijom jer je MIP-ov rast multiplikativan
(`S * D * H * R`) dok CP ostaje linearan (`5 * S`).

Izmereni broj MIP promenljivih je nizi od gornje granice `S * D * H * R`
(za MATF-L: 762 * 5 * 12 * 29 = 1,325,880) zato sto se promenljive za
nedozvoljene ucionice uopste ne kreiraju. Posto zahtev za racunarima zavisi
od tipa casa, suzenje se odnosi samo na 116 od 762 sesija.

### 7.2 Vreme resavanja (feasibility)

| Skala  | CP vreme | MIP vreme | Odnos | CP status | MIP status |
|--------|----------|-----------|-------|-----------|------------|
| MATF-S | 0.04 s   | 3.39 s    | 96x   | FEASIBLE  | FEASIBLE   |
| MATF-M | 0.11 s   | 12.05 s   | 110x  | FEASIBLE  | FEASIBLE   |
| MATF-L | 0.90 s   | 48.13 s   | 54x   | FEASIBLE  | FEASIBLE   |

Kljucni nalaz: **CP-SAT je 54-110x brzi** na svim skalama. Na MATF-L skali CP
zavrsava za manje od sekunde, dok MIP-u treba blizu minuta, od cega skoro pola
odlazi na samu konstrukciju modela.

### 7.3 Memorija

| Skala  | CP model (KB) | MIP model (KB) | Faktor |
|--------|---------------|----------------|--------|
| MATF-S | 217           | 29,928         | 138x   |
| MATF-M | 412           | 83,151         | 202x   |
| MATF-L | 747           | 270,176        | 362x   |

CP modeli zauzimaju manje od 1 MB u svim skalama, dok MIP model na MATF-L
skali prelazi 260 MB.

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

1. **Velicina modela** -- linearna umesto multiplikativne (**109-258x**
   manje promenljivih).
2. **Vreme resavanja** -- **54-110x brze** na svim skalama; na MATF-L
   (762 sesije) CP zavrsi za 0.90 s, MIP za 48.13 s.
3. **Memorija** -- **138-362x** manje za model.
4. **Skalabilnost** -- CP-SAT uspesno resava problem sa 762 sesije i 29
   ucionica za manje od sekunde, sto omogucuje interaktivnu upotrebu.
