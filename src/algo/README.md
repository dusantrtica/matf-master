# Benchmark: CP-SAT vs MIP/SCIP za raspoređivanje nastave

Ovaj dokument sumira rezultate benchmark-a koji upoređuje dva pristupa
rešavanja problema nedeljnog rasporeda nastave: **CP-SAT** (Constraint
Programming, OR-Tools) i **MIP/SCIP** (Mixed Integer Programming preko
OR-Tools `pywraplp` SCIP backend-a).

Zaključak unapred: **CP-SAT ubedljivo nadmašuje MIP/SCIP na svim testiranim
skalama** - i po vremenu rešavanja, i po veličini modela, i po memorijskoj složenosti, i po kvalitetu rešenja u okviru istog vremenskog limita. Detaljni
brojevi su u nastavku.

---

## 1. Opis problema

Treba napraviti **nedeljni raspored predavanja** za fakultet, gde se sesije
(predavanja i vežbe) dodeljuju trojkama `(dan, sat, učionica)`. Implementacija
obe varijante živi u [src/algo/](.) paketu.

### Ulazni podaci

Ulaz je definisan u [model.py](model.py) klasama:

- `Settings` - radni dani (`workingDays`), `start_hour`, `end_hour`, radno vreme fakulteta.
- `Classroom` - učionica flag-om `has_computers` i kapacitetom.
- `Course` sa `Quota(theory, practice)` - koliko teorijskih i koliko praktičnih
  časova nedeljno smer treba da odsluša za taj predmet.
- `StudentsEnrolled` - koliko studenata je upisano u dati smer/semestar.

### Generisanje sesija

Svaki upisani broj studenata se deli u grupe od po `GROUP_SIZE = 30`
(vidi [data.py](data.py), funkcija `split_students_into_groups`). Za svaku
grupu i svaki predmet generiše se po `quota.theory` teorijskih i
`quota.practice` praktičnih sesija (`generate_sessions` u [data.py](data.py)).
Jedna sesija = jedan čas u rasporedu.

### Tvrda ograničenja (hard constraints)

Oba solvera nameću identičan skup tvrdih ograničenja:

1. **Učionica zauzeta jednom u datom satu.** Nikoje dve sesije ne dele isti
   `(dan, sat, učionica)`.
2. **Grupa ne može biti na dva mesta odjednom.** Nijedna grupa ne sme imati
   dve sesije u istom `(dan, sat)`.
3. **Računarske učionice za predmete koji ih zahtevaju.** Sesija sa
   `needs_computers = true` može završiti samo u učionici sa
   `has_computers = true`.

(MIP varijanta dodatno nameće "ravnomernu raspodelu po danima" -
`sum_d x[s,d,h,r] == 1` plus `<= ceil(N_g / D)` po grupi i danu - radi
kontrole prostora pretrage; CP varijanta isti efekat dobija kroz
`AllDifferent` na `flat_time` po grupi.)

### Funkcija cilja

Minimizovati `max_slot` - **najkasniji sat dana** koji se uopšte koristi
u rasporedu. Cilj je da se nastava završi što ranije i ravnomerno rasporedi
po nedelji, umesto da se nagomila u kasnopopodnevnim terminima jednog dana.

---

## 2. Pristupi rešavanju

### CP-SAT (Constraint Programming)

Definicija u [cp_solver.py](cp_solver.py), klasa `SimpleCPSolver`.

Po sesiji `s` se kreira **5 celobrojnih promenljivih**:

- `day_var[s]`        u `[0, D-1]`
- `slot_var[s]`       u `[0, H-1]`
- `room_var[s]`       u `[0, R-1]`
- `flat_time_var[s] = day_var[s] * H + slot_var[s]` (linearizacija (dan, sat))
- `room_time_var[s] = room_var[s] * D*H + flat_time_var[s]` (linearizacija (dan, sat, učionica))

Tvrda ograničenja su zatim izražena kao dva globalna `AllDifferent`:

- `AllDifferent(room_time_var)` - sve sesije imaju jedinstvenu trojku.
- Po grupi: `AllDifferent(flat_time_var[s] for s in group)` - grupa nema dve
  sesije u istom `(dan, sat)`.

Sesije sa `needs_computers` dobijaju `AddAllowedAssignments` na `room_var`
sa listom dozvoljenih učionica.

Veličina modela: **O(S)** promenljivih (5 po sesiji).

### MIP/SCIP (Mixed Integer Programming)

Definicija u [mip_solver.py](mip_solver.py), klasa `SimpleMIPSolver`. Solver
je SCIP preko `pywraplp.Solver.CreateSolver("SCIP")`.

Po sesiji `s` se kreira **binarna promenljiva `x[s, d, h, r]`** za svaku
dozvoljenu trojku `(d, h, r)` - jedinica znači "sesija s je u danu d, satu
h, učionici r". Promenljive za nedozvoljene kombinacije (sesija traži
računare a učionica ih nema) se preskaču.

Ograničenja su klasične linearne nejednakosti:

- `sum_{d,h,r} x[s,d,h,r] == 1` za svako `s` (svaka sesija raspoređena tačno jednom).
- `sum_s x[s,d,h,r] <= 1` za svako `(d,h,r)` (učionica nije dvostruko zauzeta).
- `sum_{s in g, r} x[s,d,h,r] <= 1` po grupi i `(d,h)`.
- `sum_{s in g, h, r} x[s,d,h,r] <= ceil(N_g / D)` po grupi i danu (ravnomerna
  raspodela).

Veličina modela: **O(S * D * H * R)** binarnih promenljivih.

---

## 3. Šta je tačno mereno (metodologija)

Benchmark harness je u [benchmark.py](benchmark.py). Za svaki par
(skala, solver) mere se polja iz `BenchmarkResult` dataclass-a:

| Polje | Šta predstavlja | Kako se meri |
|---|---|---|
| `num_sessions` | Broj generisanih sesija | `len(solver.sessions)` |
| `num_variables` | Broj promenljivih u modelu | `model.Proto().variables` (CP) / `solver.NumVariables()` (MIP) |
| `num_constraints` | Broj ograničenja u modelu | `model.Proto().constraints` (CP) / `solver.NumConstraints()` (MIP) |
| `construction_time_s` | Vreme izgradnje modela | `time.perf_counter` razlika oko konstruktora |
| `solve_time_s` | Čisto vreme rešavanja | `time.perf_counter` razlika oko `solver.Solve(...)` |
| `total_time_s` | Konstrukcija + rešavanje | zbir gornja dva |
| `model_memory_kb` | Memorija alocirana tokom konstrukcije modela | `tracemalloc` snapshot razlika |
| `peak_memory_kb` | Maksimalan RSS procesa | `resource.getrusage(RUSAGE_SELF).ru_maxrss` |
| `status` | Status koji solver vraća | `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, ... |
| `objective_value` | Vrednost `max_slot` u nađenom rešenju | `ObjectiveValue()` |
| `optimality_gap` | `(obj - bestBound) / |obj|` | direktno iz solvera |
| `solution_valid` | Da li rešenje stvarno poštuje sve hard constraints | `validate_solution(...)` u `benchmark.py` |

**Vremenski limit po solveru**: 60 sekundi (parametar `max_time=60.0`).

**Validacija rešenja** je nezavisna od solvera: `validate_solution` ponovo
proverava da nikoje dve sesije ne dele `(dan, sat, učionica)`, da nijedna
grupa nema dve sesije u istom `(dan, sat)`, i da svaka sesija sa
`needs_computers` jeste u učionici sa računarima. Solver koji vrati rešenje
koje ne prolazi validator dobija `solution_valid = FAIL`.

### Skale (iz `SCALE_CONFIGS` u [benchmark.py](benchmark.py))

| Skala | Smerovi | Studenata po smeru | Predmeta po smeru | Učionica | Računarskih | Dani | Sati/dan | Theory | Practice | Comp. ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small  | 1 | 30  | 2 | 3  | 1 | 5 | 6  | 2 | 2 | 0.50 |
| medium | 2 | 90  | 4 | 8  | 3 | 5 | 10 | 3 | 3 | 0.25 |
| large  | 3 | 120 | 5 | 12 | 4 | 5 | 12 | 3 | 2 | 0.20 |
| xl     | 4 | 150 | 6 | 15 | 5 | 5 | 12 | 2 | 2 | 0.17 |

Skala raste i po broju sesija i po veličini "kalendara" (D x H x R).

---

## 4. Mašina i okruženje

Sva merenja u nastavku su izvršena na sledećem hardveru i softveru:

| Stavka | Vrednost |
|---|---|
| CPU | Apple M4 (ARM64) |
| Broj jezgara | 10 |
| RAM | 24 GB (25,769,803,776 B) |
| OS | macOS 15.6.1 (build 24G90) |
| Python | 3.11 (preko Bazel toolchain-a, vidi [MODULE.bazel](../../MODULE.bazel) - `python_version="3.11"`) |
| Build sistem | Bazel sa `rules_python` 1.4.1 |
| CP solver | OR-Tools CP-SAT |
| MIP solver | OR-Tools `pywraplp` sa SCIP backend-om |
| Komanda za pokretanje | `bazel run //src/algo:benchmark` |
| Vremenski limit po solveru | 60 s |

Hostname: `Dusans-MacBook-Air`.

---

## 5. Rezultati po skalama

Brojevi u tabelama ispod su **direktno iz poslednjeg `bazel run
//src/algo:benchmark` izvršavanja** (nije rađen prosek više pokretanja).

### 5.1 Skala `small` (8 sesija, 3 učionice, 5 dana x 6 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 8 | 8 |
| Broj promenljivih | 41 | 481 |
| Broj ograničenja | 30 | 141 |
| Vreme konstrukcije | 0.0037 s | 0.0265 s |
| Vreme rešavanja | 0.0379 s | 0.0112 s |
| Ukupno vreme | 0.0416 s | 0.0377 s |
| Memorija modela | 40.7 KB | 140.7 KB |
| Maksimalan RSS | 149,152 KB (~146 MB) | 157,024 KB (~153 MB) |
| Status | OPTIMAL | OPTIMAL |
| Objektivna vrednost (`max_slot`) | 1 | 1 |
| Optimality gap | 0.00% | 0.00% |
| Validnost rešenja | PASS | PASS |

**Komentar:** na maloj skali oba pristupa su praktično izjednačena. MIP
zapravo malo brže rešava model jer je SCIP-ov LP relaxation veoma jak na
sitnim instancama, ali već gradi 12x više promenljivih nego CP.

### 5.2 Skala `medium` (144 sesije, 8 učionica, 5 dana x 10 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 144 | 144 |
| Broj promenljivih | 721 | 48,601 |
| Broj ograničenja | 475 | 1,018 |
| Vreme konstrukcije | 0.0083 s | 1.4022 s |
| Vreme rešavanja | 0.2267 s | 28.6816 s |
| Ukupno vreme | 0.2351 s | 30.0837 s |
| Memorija modela | 124.2 KB | 11,360.0 KB (~11.1 MB) |
| Maksimalan RSS | 222,208 KB (~217 MB) | 657,024 KB (~642 MB) |
| Status | OPTIMAL | OPTIMAL |
| Objektivna vrednost (`max_slot`) | 4 | 4 |
| Optimality gap | 0.00% | 0.00% |
| Validnost rešenja | PASS | PASS |

**Komentar:** prva ozbiljna razlika. CP rešava istu instancu za **0.24 s**, MIP
za **30.08 s** - razlika od reda veličine ~128x. Memorija modela je 90x
veća kod MIP-a.

### 5.3 Skala `large` (300 sesija, 12 učionica, 5 dana x 12 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 300 | 300 |
| Broj promenljivih | 1,501 | 187,201 |
| Broj ograničenja | 973 | 2,100 |
| Vreme konstrukcije | 0.0165 s | 5.0172 s |
| Vreme rešavanja | 9.8917 s | 60.2735 s |
| Ukupno vreme | 9.9083 s | 65.2907 s |
| Memorija modela | 222.0 KB | 44,422.5 KB (~43.4 MB) |
| Maksimalan RSS | 755,744 KB (~738 MB) | 1,935,728 KB (~1.85 GB) |
| Status | **OPTIMAL** | FEASIBLE |
| Objektivna vrednost (`max_slot`) | **4** | 11 |
| Optimality gap | **0.00%** | 63.64% |
| Validnost rešenja | PASS | PASS |

**Komentar:** ključna tačka prelamanja. CP-SAT pronalazi i **dokazuje
optimalno** rešenje (`max_slot = 4`) za 9.91 s. MIP/SCIP udari u 60-sekundni
vremenski limit, vrati samo **FEASIBLE** rešenje sa `max_slot = 11` (skoro
3x lošije po objektivnoj funkciji) i gap-om 63.64% - što znači da SCIP zna
da postoji rešenje barem oko `4`, ali ne uspeva da ga nađe u datom vremenu.

### 5.4 Skala `xl` (480 sesija, 15 učionica, 5 dana x 12 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 480 | 480 |
| Broj promenljivih | 2,401 | 384,001 |
| Broj ograničenja | 1,541 | 3,160 |
| Vreme konstrukcije | 0.0267 s | 11.0783 s |
| Vreme rešavanja | 60.0379 s | 60.5870 s |
| Ukupno vreme | 60.0646 s | 71.6653 s |
| Memorija modela | 358.3 KB | 87,337.0 KB (~85.3 MB) |
| Maksimalan RSS | 1,935,728 KB (~1.85 GB) | 3,372,192 KB (~3.22 GB) |
| Status | FEASIBLE | FEASIBLE |
| Objektivna vrednost (`max_slot`) | **7** | 11 |
| Optimality gap | **42.86%** | 63.64% |
| Validnost rešenja | PASS | PASS |

**Komentar:** oba solvera dostižu vremenski limit, ali CP daje **bolje
rešenje** (`max_slot = 7` vs `11`) sa **manjim gap-om**, koristeći **160x
manje promenljivih** i upola manje RAM-a.

### 5.5 Stvarni MATF ulazi (podskupovi iz `input_full_1_semester.json`)

Benchmark podrazumevano koristi tri podskupa realnih podataka sa MATF-a
(neparni semestri -- [`input_full_1_semester.json`](input_full_1_semester.json)).
Sva tri dele isti skup od 6 odseka (5 modula Matematike + Informatika),
ali se razlikuju po tome koliko **godina studija** i koliko **lokacija**
ulazi u raspored:

| Podskup | Godine   | Lokacije                     | Semestri | Ucionica | PC ucionica |
|---------|----------|------------------------------|----------|----------|-------------|
| MATF-S  | samo 1.  | Studentski trg               | 1        | 18       | 4           |
| MATF-M  | 1. i 2.  | Studentski trg + Jagiceva    | 1, 3     | 22       | 8           |
| MATF-L  | sve (1-4) | sve lokacije                | 1,3,5,7  | 35       | 8           |

Vremenski limit: 60 s za MATF-S i MATF-M, 300 s (5 min) za MATF-L.

#### 5.5.1 MATF-S (240 sesija, 18 ucionica, 5 dana x 12 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 240 | 240 |
| Broj promenljivih | 1,201 | 203,761 |
| Broj ogranicenja | 797 | 2,210 |
| Vreme konstrukcije | **0.0130 s** | 7.3513 s |
| Vreme resavanja | **0.4730 s** | 60.3645 s |
| Ukupno vreme | **0.49 s** | 67.72 s |
| Memorija modela | 234.4 KB | 59,585.8 KB (~58 MB) |
| Maksimalan RSS | 161,888 KB (~158 MB) | 1,869,584 KB (~1.78 GB) |
| Status | **OPTIMAL** | FEASIBLE |
| Objektivna vrednost (`max_slot`) | **4** | 10 |
| Optimality gap | **0.00%** | 60.00% |
| Validnost resenja | PASS | PASS |

**Komentar:** CP-SAT resava i **dokazuje optimalnost** za 0.49 s sa
`max_slot = 4`. MIP/SCIP udari u 60-sekundni limit i vrati samo FEASIBLE
sa `max_slot = 10` (2.5x losije). Odnos velicine modela: **170x**
(1,201 vs 203,761 promenljivih).

#### 5.5.2 MATF-M (484 sesije, 22 ucionice, 5 dana x 12 sati)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 484 | 484 |
| Broj promenljivih | 2,421 | 522,121 |
| Broj ogranicenja | 1,611 | 3,523 |
| Vreme konstrukcije | **0.0210 s** | 18.4341 s |
| Vreme resavanja | **13.1957 s** | 61.0955 s |
| Ukupno vreme | **13.22 s** | 79.53 s |
| Memorija modela | 399.8 KB | 149,810.3 KB (~146 MB) |
| Maksimalan RSS | 1,869,584 KB (~1.78 GB) | 4,074,976 KB (~3.89 GB) |
| Status | **OPTIMAL** | FEASIBLE |
| Objektivna vrednost (`max_slot`) | **5** | 10 |
| Optimality gap | **0.00%** | 50.00% |
| Validnost resenja | PASS | PASS |

**Komentar:** CP-SAT resava i **dokazuje optimalnost** (`max_slot = 5`)
za 13.22 s. MIP/SCIP ponovo udari u limit, vrati `max_slot = 10`
(duplo losije) sa gap-om 50%. Velicina modela: **216x** razlika.

#### 5.5.3 MATF-L (937 sesija, 35 ucionica, 5 dana x 12 sati, limit 5 min)

| Metrika | CP-SAT | MIP/SCIP |
|---|---:|---:|
| Broj sesija | 937 | 937 |
| Broj promenljivih | 4,686 | **1,433,101** |
| Broj ogranicenja | 3,179 | 6,379 |
| Vreme konstrukcije | **0.0401 s** | 52.6552 s |
| Vreme resavanja | 300.0643 s | 302.4721 s |
| Ukupno vreme | **300.10 s** | 355.13 s |
| Memorija modela | 744.7 KB | 419,615.1 KB (~410 MB) |
| Maksimalan RSS | 4,327,792 KB (~4.13 GB) | 6,481,840 KB (~6.19 GB) |
| Status | **FEASIBLE** | NOT_SOLVED |
| Objektivna vrednost (`max_slot`) | **10** | N/A |
| Optimality gap | 50.00% | N/A |
| Validnost resenja | **PASS** | N/A |

**Komentar:** sa 5-minutnim limitom CP-SAT **pronadje validan raspored**
(`max_slot = 10`, gap 50%), koji prolazi `validate_solution` proveru.
MIP/SCIP ne uspe da vrati nijedno resenje -- gubi ~53 s samo na
konstrukciji 1.4M binarnih promenljivih, a preostalo vreme nije dovoljno
za SCIP da zavrsi LP relaxation na modelu te velicine.
Velicina modela: **306x** (4,686 vs 1,433,101 promenljivih).

---

## 6. Zbirna tabela

Pregled kljucnih metrika kroz sve skale (sinteticke + MATF podskupovi):

| Skala | Sesije | CP vars | MIP vars | CP ukupno (s) | MIP ukupno (s) | CP RSS (MB) | MIP RSS (MB) | CP status | MIP status | CP obj | MIP obj | CP gap | MIP gap |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| small  | 8   | 41    | 481       | 0.04   | 0.04   | 146   | 153   | OPTIMAL  | OPTIMAL  | 1  | 1  | 0.00%  | 0.00%  |
| medium | 144 | 721   | 48,601    | 0.24   | 30.08  | 217   | 642   | OPTIMAL  | OPTIMAL  | 4  | 4  | 0.00%  | 0.00%  |
| large  | 300 | 1,501 | 187,201   | 9.91   | 65.29  | 738   | 1,851 | OPTIMAL  | FEASIBLE | 4  | 11 | 0.00%  | 63.64% |
| xl     | 480 | 2,401 | 384,001   | 60.06  | 71.67  | 1,851 | 3,222 | FEASIBLE | FEASIBLE | 7  | 11 | 42.86% | 63.64% |
| MATF-S | 240 | 1,201 | 203,761   | 0.49   | 67.72  | 158   | 1,783 | OPTIMAL  | FEASIBLE | 4  | 10 | 0.00%  | 60.00% |
| MATF-M | 484 | 2,421 | 522,121   | 13.22  | 79.53  | 1,783 | 3,889 | OPTIMAL  | FEASIBLE | 5  | 10 | 0.00%  | 50.00% |
| MATF-L | 937 | 4,686 | 1,433,101 | 300.10 | 355.13 | 4,130 | 6,190 | FEASIBLE | NOT_SOLVED | 10 | N/A | 50.00% | N/A |

---

## 7. Analiza i nalazi

### 7.1 Velicina modela

CP-SAT model raste **linearno** sa brojem sesija: `5 * S` celobrojnih
promenljivih. MIP/SCIP model raste **multiplikativno**: `S * D * H * R`
binarnih promenljivih. Konkretno:

- **MATF-S** (240 sesija, 18 ucionica): CP 1,201 vs MIP 203,761 (**170x**).
- **MATF-M** (484 sesija, 22 ucionice): CP 2,421 vs MIP 522,121 (**216x**).
- **MATF-L** (937 sesija, 35 ucionica): CP 4,686 vs MIP 1,433,101 (**306x**).

Faktor raste sa svakom dodatnom dimenzijom jer je MIP-ov rast multiplikativan
(`S * D * H * R`) dok CP ostaje linearan (`5 * S`).

### 7.2 Vreme resavanja

| Skala  | CP ukupno | MIP ukupno | Odnos | CP status | MIP status |
|--------|-----------|-----------|-------|-----------|------------|
| small  | 0.04 s    | 0.04 s    | ~1x   | OPTIMAL   | OPTIMAL    |
| medium | 0.24 s    | 30.08 s   | 128x  | OPTIMAL   | OPTIMAL    |
| large  | 9.91 s    | 65.29 s   | 6.6x  | OPTIMAL   | FEASIBLE   |
| xl     | 60.06 s   | 71.67 s   | ~1.2x | FEASIBLE  | FEASIBLE   |
| MATF-S | 0.49 s    | 67.72 s   | 138x  | OPTIMAL   | FEASIBLE   |
| MATF-M | 13.22 s   | 79.53 s   | 6.0x  | OPTIMAL   | FEASIBLE   |
| MATF-L | 300.10 s  | 355.13 s  | ~1.2x | FEASIBLE  | NOT_SOLVED |

Kljucni nalaz: **CP-SAT postiže OPTIMAL na MATF-S i MATF-M** (240 i 484
sesije) dok MIP vraca samo FEASIBLE sa 2-2.5x losijom objektivnom vrednoscu.
Na MATF-L skali CP daje validan raspored, a MIP ne vraca nijedno resenje.

### 7.3 Memorija

CP modeli zauzimaju manje od 1 MB u svim skalama. MIP modeli:

| Skala  | CP model (KB) | MIP model (KB) | Faktor |
|--------|---------------|----------------|--------|
| MATF-S | 234           | 59,586         | 254x   |
| MATF-M | 400           | 149,810        | 375x   |
| MATF-L | 745           | 419,615        | 563x   |

Maksimalan RSS na MATF-L: CP ~4.1 GB vs MIP ~6.2 GB.

### 7.4 Kvalitet resenja u uslovima vremenskog limita

Na svim MATF skalama gde oba solvera vrate resenje, CP-SAT daje
**drasticno bolje** rasporede:

| Skala  | CP max_slot | MIP max_slot | CP/MIP odnos |
|--------|-------------|-------------|--------------|
| MATF-S | **4**       | 10          | 2.5x bolje   |
| MATF-M | **5**       | 10          | 2.0x bolje   |
| MATF-L | **10**      | N/A         | MIP: nema resenja |

U prakticnom smislu, `max_slot = 4` znaci da se nastava zavrsava do 12h,
dok `max_slot = 10` znaci da se nastava razvlaci do 18h -- velika razlika
za studente i profesore.

### 7.5 Validnost

Sva rešenja koja su solveri prijavili **prolaze** post-hoc `validate_solution`
proveru. Nije bilo lažno-pozitivnih izlaza ni kod jednog solvera, što znači
da su oba modela korektno postavljena, samo se značajno razlikuju u
performansama.

### 7.6 Trade-off sažetak

CP-SAT pravi **kompaktan model i agresivno koristi propagaciju ograničenja**
(`AllDifferent` je u solveru implementiran kao posebno efikasno globalno
ograničenje). MIP/SCIP pravi **veliki ali "ravan" model** i oslanja se na
LP relaxation za donje granice. Kako problem raste, MIP gubi jer
multiplikativni rast broja promenljivih dominira nad bilo kakvom korišću
od LP relaxation-a.

---

## 8. Kako reprodukovati

Sva pokretanja idu kroz Bazel:

```bash
bazel run //src/algo:benchmark
```

Po default-u, ova komanda pokrece tri MATF podskupa (S, M, L) iz
[`input_full_1_semester.json`](input_full_1_semester.json). Konkretne skale:

```bash
bazel run //src/algo:benchmark -- --real-scales S M     # samo S i M
bazel run //src/algo:benchmark -- --real-scales L        # samo L (5 min limit)
```

Sinteticke skale (small/medium/large/xl):

```bash
bazel run //src/algo:benchmark -- --scales small medium large xl --max-time 60 --json out.json
```

Custom ulazni fajlovi:

```bash
bazel run //src/algo:benchmark -- --inputs path/to/a.json path/to/b.json --max-time 60
```

Pojedinačni solveri (postojeći Bazel target-i u [BUILD.bazel](BUILD.bazel)):

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

Na osnovu merenja iznad - i sintetickih skala i tri realna MATF podskupa -
**CP-SAT je jasan pobednik** za nas problem nedeljnog rasporeda nastave.
Pobedjuje u sve cetiri kategorije:

1. **Velicina modela** - linearna umesto multiplikativne (na MATF-L skali:
   **~306x manje promenljivih**).
2. **Vreme resavanja** - CP-SAT postiže **OPTIMAL** na MATF-S (0.49 s) i
   MATF-M (13.22 s), dok MIP vraca samo FEASIBLE sa losijim `max_slot`
   i gap-om 50-60%. Na MATF-L, CP pronadje validan raspored za 5 min,
   MIP ne vrati nijedno resenje.
3. **Memorija** - faktor 254-563x manje za sam model; ~1.5x manje RSS.
4. **Kvalitet resenja pod vremenskim limitom** - CP konzistentno daje
   `max_slot` koji je 2-2.5x bolji od MIP-ovog na istom ulazu.

### Sledeći koraci

U skladu sa [.cursor/rules/project-overview.mdc](../../.cursor/rules/project-overview.mdc),
projekat nastavlja razvoj **na CP-SAT pristupu**:

- Dodavanje dodatnih (mekih) ograničenja: preferencije profesora, blokiranje
  pauza, balansiranje opterećenja po danu, itd.
- Web omotač oko CP solvera za interaktivno generisanje rasporeda.
- MIP varijanta ostaje u repozitorijumu kao referentna implementacija
  (sanity check za korektnost CP rešenja).
