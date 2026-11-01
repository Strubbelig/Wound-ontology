Universality reading of the 1,007 relations that pass rule 66 (>= 2 abstracts,
both ends typed right). Read by Claude, 2026-10-02, on the curator's "do it
yourself". One line per row: `<id> <all|some|no>  # note`.

A row `C | R | T` is read as the OWL axiom it would become:
    C SubClassOf (R some T)      -- EVERY instance of C stands in R to some T.

  all   the axiom is true of every instance of C
        (`Burn injury has_quality depth`: every burn has some depth).
  some  true of some instances only, so NOT an axiom
        (`Wound has_quality contaminated`: there are clean wounds;
         `X participates_in wound healing`: not every wound heals or is treated;
         `amputation risk has_realization amputation`: not every risk is realized;
         `area inheres_in Wound`: not every area is a wound's).
  no    false or not a sound statement:
        - a subclass statement misread as part-hood (`Acute wound part_of Wound`,
          `Chronic wound has_part Diabetic foot ulcer`, `amputation part_of
          surgical procedure`, `antibiotic has_part meropenem`);
        - a self-loop (`Burn injury part_of Burn injury`);
        - the wrong bearer (`Burn injury has_quality total body surface area`:
          that is the body's quality, not the burn's);
        - a vague or study-local term (`index extremity`, `sustained release`).

Strict: when unsure between all and some, some. Only `all` may become an axiom.
