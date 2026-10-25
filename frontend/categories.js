// Shared detailed garment-category metadata — mirrors the backend's central
// registry (backend/app/categories.py). Loaded by every page that displays
// or edits items: the category is the primary display value; the broad type
// is derived from it and used only as a grouping/filter aid.
"use strict";

const CATEGORY_GROUPS = [
  { type: "top", label: "Tops", items: [
    ["t_shirt", "T-shirt"], ["shirt", "Shirt"], ["blouse", "Blouse"],
    ["polo", "Polo"], ["tank_top", "Tank top"], ["vest", "Vest"],
    ["sweater", "Sweater"], ["cardigan", "Cardigan"], ["hoodie", "Hoodie"],
    ["sweatshirt", "Sweatshirt"], ["dress", "Dress"],
    ["jumpsuit", "Jumpsuit"], ["romper", "Romper"],
    ["other_top", "Other top"],
  ] },
  { type: "bottom", label: "Bottoms", items: [
    ["jeans", "Jeans"], ["trousers", "Trousers"], ["chinos", "Chinos"],
    ["skirt", "Skirt"], ["shorts", "Shorts"], ["leggings", "Leggings"],
    ["joggers", "Joggers"], ["tights", "Tights"],
    ["thermal_leggings", "Thermal leggings"], ["other_bottom", "Other bottom"],
  ] },
  { type: "shoes", label: "Shoes", items: [
    ["sneakers", "Sneakers"], ["boots", "Boots"], ["loafers", "Loafers"],
    ["derbies", "Derbies"], ["heels", "Heels"], ["flats", "Flats"],
    ["sandals", "Sandals"], ["other_shoes", "Other shoes"],
  ] },
  { type: "outerwear", label: "Outerwear", items: [
    ["denim_jacket", "Denim jacket"], ["bomber_jacket", "Bomber jacket"],
    ["blazer", "Blazer"], ["trench_coat", "Trench coat"], ["coat", "Coat"],
    ["puffer_jacket", "Puffer jacket"], ["rain_jacket", "Rain jacket"],
    ["other_outerwear", "Other outerwear"],
  ] },
  { type: "accessory", label: "Accessories", items: [
    ["belt", "Belt"], ["scarf", "Scarf"], ["hat", "Hat"], ["cap", "Cap"],
    ["beanie", "Beanie"], ["watch", "Watch"], ["bag", "Bag"],
    ["jewellery", "Jewellery"], ["other_accessory", "Other accessory"],
  ] },
];

const TYPE_OF_CATEGORY = Object.fromEntries(
  CATEGORY_GROUPS.flatMap((g) => g.items.map(([value]) => [value, g.type]))
);

const CATEGORY_LABEL = Object.fromEntries(
  CATEGORY_GROUPS.flatMap((g) => g.items)
);

// Worn instead of a primary top + bottom; the form flags them.
const ONE_PIECE_CATEGORIES = new Set(["dress", "jumpsuit", "romper"]);
