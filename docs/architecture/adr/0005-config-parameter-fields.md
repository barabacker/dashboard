# ADR 0005 — `ConfigForm` renders one field per `ParamSpec`, not raw JSON

Status: accepted · Date: 2026-07-31

## Context

After ADR 0004 split `Source` (site identity) from `Config` (a named collection profile), the
profile still authored its own behavioural parameters — `max_pages`, `only_active`, `concurrency`,
and (for `tender_fogsoft`) `fetch_details` — as a single raw JSON blob (`ConfigForm.parameters`).
This was the deferred half of the very first design question in this series: build the form
statically per collector, or generate it from the collector's own `ParamSpec` list. ADR 0004 chose
the dynamic answer for `Source`'s TLS/domain fields' presentation nuances; the same question stood
open for `Config`'s own behavioural parameters.

A short review of the four remaining parameters, prompted by "what should stay authorable versus
move into code," confirmed all four earn their keep:

- `fetch_details` is literally the `full`/`fast` axis this whole profile system exists to support.
- `only_active` is a genuine operational choice (archive vs. active-only), not a constant.
- `max_pages` is, by its own schema description, a debugging knob — rarely touched, but exactly the
  kind of thing that needs to stay reachable from the admin when it *is* needed.
- `concurrency` looked like a removal candidate at first (no carried-over site in `seed_sources`
  has ever set it away from the default of `1`), but the engine's own tests
  (`test_kendo_crawl_is_correct_under_higher_concurrency`) prove it is a working, tested lever —
  the reason nobody has used it yet is that no site has needed the speed, not that the lever is
  vestigial. Removing a tested capability on the strength of "nobody's touched it" would be
  premature.

So nothing moves into code; the form work is the whole of this decision.

## Decision

### 1. `ConfigForm` builds one field per `ParamSpec`, mapped by `kind`

The same closed `kind → Django field` mapping the earlier `SourceForm` design sketched (and never
needed, since `Source`'s own fields turned out to be plain model fields) is implemented here:
`str → CharField`, `int → IntegerField` (with `min_value`/`max_value`), `float → FloatField`,
`bool → BooleanField` (always `required=False` — an unchecked box is a valid `False`, not a missing
value), `list`/`dict → JSONField`; a `choices` tuple on the `ParamSpec` overrides the type mapping
with a `ChoiceField` regardless of `kind`. `is_credential_ref` prefixes the help text
("Ссылка на секрет...") rather than changing the widget — no current parameter needs more than
that.

Fields the collector's schema also shares with `Source` (`domain`, `listing_path`, `extra_ca_cert`,
`skip_tls_verify` — see `Source.PARAM_FIELDS`, a single named constant both `Config.raw_parameters`
and `ConfigForm` import rather than each hardcoding the same four names) are skipped: they are
supplied by the profile's `source`, not re-asked on the profile itself.

### 2. Only one collector's fields are ever rendered — reload, not JS

Confirmed with the user as the mechanics answer to the question ADR 0004 deferred: the
`collector_key` dropdown's `onchange` navigates to `?collector_key=<key>` on the same add page (no
JS framework), which Django's own unmodified `get_changeform_initial_data` already folds into the
form's `initial`. `ConfigForm._current_collector_key` resolves, in order: what was actually
submitted (a bound form), the instance's own value (editing an existing profile), the `initial`
value (the reload), or the first known collector (a fresh, untouched add page has to show
*something*). Because exactly one collector's parameters are ever in the DOM at a time, there is no
field-name collision risk between collectors — the concern the "show every collector's fields, hide
the wrong ones with CSS" alternative would have carried.

### 3. Admin wiring needed two non-obvious overrides

Fitting a form whose field *set* varies per request into Django admin's fieldset machinery required
two overrides on `ConfigAdmin`, both because Django's own `get_form()`/`get_fieldsets()` assume a
static field list:

- **`get_fieldsets()`** builds a throwaway `ConfigForm` instance (bound the same way the real one
  will be) purely to read `probe._param_field_names` and interpolate them into the `(None, {...})`
  section. It instantiates `self.form` directly rather than calling `self.get_form(request, obj)`:
  Django's default `get_form()` calls back into `get_fieldsets()` to compute its own `fields=`
  argument, so calling it from here recurses.
- **`get_form()`** is overridden to call `modelform_factory(self.model, form=self.form,
  formfield_callback=...)` directly, with no `fields=`/`exclude=` override — letting it fall back
  to `ConfigForm.Meta`'s own static field list (`name`/`collector_key`/`source`/`enabled`/
  `archived`/`tags`/`owner`, never a dynamic parameter name). Django's *default* `get_form()`
  instead passes `fields=flatten_fieldsets(self.get_fieldsets(request, obj))` — which would include
  whichever collector's parameter names `get_fieldsets()` had just computed, and `modelform_factory`
  raises `FieldError` for any name that is not a real `Config` model field. The `formfield_callback`
  is kept explicitly so `source`/`owner` still get their admin widgets — including `source`'s
  "add related" popup from ADR 0004.

### 4. `ConfigInline` (under `SourceAdmin`, from the previous change) gets its own form subclass

`ConfigInline.ConfigInlineForm(ConfigForm)` overrides `_add_parameter_fields` to a no-op. Without
it, the inline — which deliberately shows only `name`/`collector_key`/`enabled` — would still have
had `ConfigForm.__init__` build the full dynamic parameter set for whatever `collector_key`
resolves to, either rendering unwanted extra columns or (worse) validating fields nobody can see.
Profiles added via the inline keep their collector's parameter defaults until edited on their own
change page, exactly as before this change.

## Consequences

- The raw-JSON `parameters` textarea is gone from the admin entirely; `Config.parameters` is still
  the storage shape (a plain dict), just never hand-edited as JSON text.
- Adding a collector whose parameters are plain `str`/`int`/`float`/`bool`/`choices` needs **no**
  `ConfigForm` change — the point of this exercise. A collector needing a materially different
  widget (a real file upload, a multi-select, ...) is the forcing factor that would reopen this
  design, not something to build against speculatively now.
- `ConfigForm.save()` is now an explicit override: since `parameters` is no longer a bound Meta
  field, nothing populates `instance.parameters` automatically, so `save()` assigns
  `self.cleaned_data.get("parameters", {})` (assembled in `clean()` from the dynamic field names)
  before calling the real save.
- `Config.parameters` for a profile can now store explicit `None` values for optional parameters
  the form rendered but the user left blank (e.g. `{"max_pages": None}`), rather than omitting the
  key the way the old hand-rolled `SourceForm._collect_parameters` used to. Harmless —
  `CollectorDescriptor.resolve()` already treats `None` the same as "missing" and applies the
  default — just a cosmetically noisier stored value than a hand-curated omission would be.
