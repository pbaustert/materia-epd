# EPD pipeline explained

This page explains **what** the ``materia_epd.epd.pipeline`` module does and
**why** its steps are organised the way they are. It is meant as an
*explanation* rather than a step‑by‑step guide or API reference.


## High‑level goals

The EPD pipeline turns:

* a collection of ILCD XML files describing **EPDs** (environmental product
  declarations), and
* a collection of ILCD XML files describing **generic processes**

into:

* synthesized **market‑representative EPDs** per process and country,
* aggregated **impact indicators** (e.g. GWP) per market,
* and updated ILCD process/flow files written to an output directory.

Conceptually, the pipeline answers:

* **Which EPDs are relevant for this process?**
* **How can we reconcile differences in units, locations and materials?**
* **What is the “average” material and environmental impact for a market?**


## Conceptual overview of the module

The main concepts in ``pipeline.py`` are:

* **XML readers**: turn ILCD XML files into Python objects.
* **filters**: decide whether a given EPD is relevant for a process.
* **location escalation**: progressively relax geographic constraints if no
  exact match is found.
* **averaging**: compute representative material properties and impacts.
* **orchestration**: connect all previous pieces over a folder tree.

The conceptual data‑flow looks like this:

```{mermaid}
flowchart TD
    A[EPD XML files folder ] -->|parse| B[IlcdProcess EPDs]
    C[Generic process XML files folder] -->|parse & enrich| D[IlcdProcess processes]
    D -->|for each process with matches| E[epd_pipeline]
    B --> E
    E --> F[Avg. materialproperties]
    E --> G[Market‑weightedimpacts per country]
    F --> H[Write updatedprocess XML]
    F --> I[Write updatedflow XML]
    G --> H
```

## XML object generation

Two small generators define how XML is brought into the pipeline:

* ``gen_xml_objects`` takes a file or folder path and yields
  ``(path, xml_root)`` pairs.
* ``gen_epds`` wraps ``gen_xml_objects`` and returns ``IlcdProcess`` instances
  representing individual EPDs.

These functions are intentionally low‑level: they abstract *file iteration and
parsing* but do not decide anything about *relevance* or *aggregation*.


## Filtering and location escalation

Filtering logic is split into composable parts:

* ``gen_filtered_epds(epds, filters)``: yields only EPDs for which *all*
  filters match (logical AND).
* Filters are instances like:

  * ``UUIDFilter`` – selects only EPDs that are explicitly matched to a
    process (via UUIDs from ``process.matches``).
  * ``UnitConformityFilter`` – ensures the EPD’s declared unit is compatible
    with the process’ material quantity description
    (``process.material_kwargs``).
  * ``LocationFilter`` – constrains the EPD to certain geographic
    locations/countries.

``gen_locfiltered_epds`` builds on top of this to implement **location
escalation**: if no EPD is found for the requested locations, it repeatedly
relaxes the location set using ``escalate_location_set`` until either:

* at least one EPD matches, or
* a maximum number of attempts is reached, in which case a
  ``NoMatchingEPDError`` is raised.

This design separates **“what we want”** (filters) from
**“how hard we try to get it”** (escalation strategy).

The escalation behaviour can be seen conceptually as:

```{mermaid}

   flowchart TD
     S[Requested locations] --> L1[Try exactmatches]
     L1 -->|no EPDs| L2[Escalate tobroader regions]
     L2 -->|no EPDs| L3[Escalate again e.g. EU, global]
     L3 -->|no EPDs after N attempts| E[NoMatchingEPDError]
     L1 -->|EPDs found| R[Use matchingEPDs]
     L2 -->|EPDs found| R
     L3 -->|EPDs found| R
```

## The ``epd_pipeline`` function

``epd_pipeline(process, path_to_epd_folder)`` is the **core conceptual unit**
of the module. For a single generic process, it:

1. **Collects candidate EPDs**

   * Parses EPD XML files from ``path_to_epd_folder``.
   * Builds an initial filter list based on:

     * ``process.matches`` (linked EPD UUIDs) → ``UUIDFilter``.
     * ``process.material_kwargs`` (functional unit description) →
       ``UnitConformityFilter``.

2. **Attempts matching in the process’ declared unit**

   * Applies the filters using ``gen_filtered_epds``.
   * If **no EPD matches**, the pipeline *conceptually* concludes that the
     process’ declared unit is too specific.

3. **Fallback to mass‑based functional unit**

   * Logs a warning that the functional unit is being switched to a
     mass‑based one (using ``MASS_KWARGS``).
   * Replaces the ``UnitConformityFilter`` accordingly.
   * Re‑evaluates the EPDs with the new unit assumptions.
   * If there are still no EPDs, the pipeline returns ``(None, None)`` as
     a signal that this process cannot be handled.

   This step encodes a **design decision**: *mass* is the ultimate fallback
   quantity when other, more specific functional units cannot be matched.

4. **Compute LCIA results for each selected EPD**

   * For every filtered EPD, the pipeline requests its life‑cycle impact
     assessment (LCIA) results via ``epd.get_lcia_results()``.
   * At this stage, the focus is on **per‑EPD impacts**, not yet on markets.

5. **Average material properties across EPDs**

   * ``average_material_properties(filtered_epds)`` computes an average
     material description (e.g. density, composition).
   * This is wrapped in a ``Material`` object, which is then rescaled to the
     process’ functional unit (``mat.rescale(process.material_kwargs)``).
   * The result is a single, representative **average material** for the
     process.

6. **Build markets and aggregate impacts**

   * For each country in ``process.market``, the pipeline selects location‑
     appropriate EPDs using ``gen_locfiltered_epds`` and ``LocationFilter``.
   * For each country, ``average_impacts`` computes an average LCIA result
     from the selected EPDs.
   * ``weighted_averages(process.market, market_impacts)`` then combines the
     per‑country impacts into **market‑weighted global warming potentials
     (GWPs)** (or other indicators, depending on configuration).

7. **Return conceptual outputs**

   * ``avg_properties`` – a dictionary of average material properties,
   * ``avg_gwps`` – weighted average impacts for the market.

Conceptually, ``epd_pipeline`` moves from **raw EPDs** to a
**market‑representative material and impact profile** for a single process.


## Orchestration via ``run_materia``

While ``epd_pipeline`` encapsulates the logic for *one* process,
``run_materia(path_to_gen_folder, path_to_epd_folder, output_path)`` explains
how the whole **folder tree** is traversed and updated:

* It first copies the generic ILCD structure from ``path_to_gen_folder`` to
  ``output_path``, excluding folders that will be regenerated or are not
  required (``"processes"``, ``"processes_old"``, ``"flows"``).
* It then iterates over each generic process XML in
  ``path_to_gen_folder / "processes"``:

  * builds an ``IlcdProcess`` instance,
  * enriches it with reference flow, declared unit, HS class, market and
    EPD matches.

* For each process that has at least one match:

  * it calls ``epd_pipeline`` to obtain ``avg_properties`` and ``avg_gwps``,
  * if those are ``None``, it logs that the process cannot be completed,
  * otherwise, it:

    * constructs a ``Material`` from ``avg_properties``,
    * writes an updated process file (embedding the aggregated impacts),
    * writes a flow file describing the averaged material,
    * logs successful completion.

``run_materia`` is responsible for:

* **scaling up** the per‑process logic of ``epd_pipeline`` to an entire
  dataset,
* keeping **file system structure** consistent between input and output,
* and providing **progress feedback** to users.


## How the pieces fit together

Putting everything together, the conceptual control‑flow looks like:

```{mermaid}

   flowchart TD
     subgraph Input
       G[Generic processes XML in gen/processes]
       E[EPDs XML in epd/processes]
     end

     subgraph Pipeline
       R[run_materia]
       P[epd_pipeline per process]
       F1[Filtering &unit conformity]
       F2[Locationescalation]
       A1[Avg. materialproperties]
       A2[Market‑weightedimpacts]
     end

     subgraph Output
       O1[Updated process XML]
       O2[Updated flow XML]
     end

     G --> R
     R -->|for each matched process| P
     E --> P
     P --> F1 --> F2 --> A1 --> A2
     A1 --> O2
     A2 --> O1
```

## TL;DR

* The pipeline treats EPDs as **evidence** that is filtered and aggregated to
  construct a representative, market‑specific view of a material.
* **Unit conformity** and **location escalation** are complementary strategies
  to make heterogeneous datasets usable without silently discarding too much
  information.
* ``run_materia`` provides the bridge between these abstract ideas and a
  concrete ILCD folder structure, but the conceptual heart of the system is
  the combination of **filters**, **escalation**, and **averaging** in
  ``epd_pipeline``.

