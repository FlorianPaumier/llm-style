# Detailed Garment Taxonomy Design

## Goal

Let a wardrobe record precise garment categories while preserving reliable,
complete, and compatible outfit recommendations.

## Data model

Each item retains its existing broad `type` as its recommendation slot:
`top`, `bottom`, `shoes`, `outerwear`, or `accessory`. A new required
`category` stores the garment's detailed classification. Existing items are
migrated with a compatible default category and newly seeded items always use
a precise category.

The supported categories and their slots are:

- `top`: `t_shirt`, `shirt`, `blouse`, `polo`, `tank_top`, `vest`,
  `sweater`, `cardigan`, `hoodie`, `sweatshirt`, `other_top`
- `bottom`: `jeans`, `trousers`, `chinos`, `skirt`, `shorts`, `leggings`,
  `joggers`, `tights`, `thermal_leggings`, `other_bottom`
- `shoes`: `sneakers`, `boots`, `loafers`, `derbies`, `heels`, `flats`,
  `sandals`, `other_shoes`
- `outerwear`: `denim_jacket`, `bomber_jacket`, `blazer`, `trench_coat`,
  `coat`, `puffer_jacket`, `rain_jacket`, `other_outerwear`
- `accessory`: `belt`, `scarf`, `hat`, `cap`, `beanie`, `watch`, `bag`,
  `jewellery`, `other_accessory`
- one-piece items: `dress`, `jumpsuit`, and `romper`, represented through a
  `top` recommendation slot for compatibility with the current persistence
  format, but assigned a `one_piece` outfit role.

## Outfit roles and compatibility

Category metadata maps every category to an outfit role. The selector and
fallback enforce the following constraints; the LLM receives the same rules
in its prompt and its response is validated against them.

- Exactly one `primary_upper` is selected for a normal outfit. `vest` is a
  primary upper, so it cannot be paired with a `blouse`, `shirt`, or T-shirt.
- `layer_upper` categories such as `cardigan` may be added over a primary
  upper when present in the candidate set.
- Exactly one `primary_lower` is selected, except when an item with the
  `one_piece` role replaces both the upper and lower.
- `lower_underlayer` categories (`tights`, `leggings`, thermal leggings) are
  optional and may be paired with a skirt, dress, or shorts. They do not
  replace a primary lower. Tights therefore work under a skirt.
- Exactly one footwear item is selected. Outerwear and accessories remain
  optional and weather-aware.

## API, storage, and migration

`category` is exposed on item create, update, list, and classification
responses. The server derives and validates its broad slot and outfit role;
clients cannot claim incompatible combinations. SQLite receives an additive
`category` column and an idempotent backfill for existing rows. Old records
receive an `other_<type>` category and can be refined in the wardrobe UI; the
current seeded database is recreated with detailed categories.

The `type` field remains in API responses during this change so current
clients and recommendation history remain compatible. The wardrobe UI makes
the category the primary selector and display value, with type shown only as
the grouping/filter aid.

## Image classification

The image-classification prompt lists the supported detailed categories and
instructs the vision model to return `category` as well as the existing
garment attributes. The backend validates that category, derives its broad
`type` and outfit role from the central category metadata, and rejects an
invalid or mismatched type/category pair instead of saving it. Single-image,
multi-item, bulk-queue, and quick-add flows all use this same validation. The
review UI displays the detailed category for every draft so the user can
correct a vision-model mistake before saving.

## Recommendation behavior

Candidate selection continues to provide compact, broad-slot candidate lists,
but includes category and role information. The stylist prompt describes
available categories and role constraints. The deterministic fallback chooses
one primary upper and lower (or a one-piece), can add a compatible layer or
underlayer, and never returns competing primary garments.

## Verification

Tests cover API validation, database backfill, category-to-slot mappings,
vision draft validation, compatibility validation, the vest/blouse conflict,
skirt plus tights, valid layering, one-piece outfits, fallback behavior,
single and multi-item image classification, and the 500-item seed
distribution.
