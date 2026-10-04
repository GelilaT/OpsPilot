"""Shared ingredient pantry the restaurant profiles draw from.

Columns: code | name | category | base unit | shelf life days | storage area | purchase unit | pack size |
base units per purchase unit | list price (major units per purchase unit) | extra conversions
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PantryItem:
    code: str
    name: str
    category: str
    base_unit: str
    shelf_life_days: int
    storage_area: str
    purchase_unit: str
    pack_size: str | None
    base_qty_per_unit: Decimal
    price: Decimal
    conversions: dict[str, Decimal] = field(default_factory=dict)


_PANTRY = """
chicken_thigh|Chicken thigh, boneless skinless|meat|g|4|walk_in|kg|5kg case|1000|6.70|
chicken_breast|Chicken breast fillet|meat|g|4|walk_in|kg|5kg case|1000|7.40|
chicken_wings|Chicken wings, jointed|meat|g|4|walk_in|kg|5kg case|1000|3.90|
beef_mince|Beef mince 15% fat|meat|g|4|walk_in|kg|5kg case|1000|7.80|
beef_patty|Beef burger patty 6oz|meat|each|5|walk_in|case|48 x 170g|48|62.40|
beef_sirloin|Beef sirloin steak|meat|g|5|walk_in|kg||1000|27.50|
pork_belly|Pork belly, boneless|meat|g|5|walk_in|kg||1000|8.20|
pork_sausage|Pork sausage, butcher's|meat|each|6|walk_in|case|60 x 67g|60|19.80|
bacon|Smoked back bacon|meat|g|10|walk_in|kg|2.27kg pack|1000|8.60|
lamb_shoulder|Lamb shoulder, boneless|meat|g|5|walk_in|kg||1000|11.90|
black_pudding|Black pudding|meat|g|14|walk_in|kg||1000|6.40|
duck_breast|Duck breast|poultry|g|5|walk_in|kg||1000|14.60|
eggs|Free-range eggs, large|poultry|each|21|walk_in|tray|30 eggs|30|7.50|
cod_fillet|Cod loin fillet|fish|g|2|walk_in|kg||1000|19.80|
salmon_fillet|Salmon fillet, skin on|fish|g|3|walk_in|kg||1000|17.40|
smoked_salmon|Smoked salmon, sliced|fish|g|10|walk_in|kg|1kg pack|1000|24.00|
prawns|King prawns, raw peeled|fish|g|90|freezer|kg|1kg bag|1000|15.90|
cos_lettuce|Cos lettuce|produce|g|5|walk_in|case|12 heads|4800|9.60|
mixed_leaves|Mixed salad leaves|produce|g|4|walk_in|kg|1kg bag|1000|6.80|
tomato|Tomatoes, vine|produce|g|7|walk_in|kg|6kg box|1000|2.20|
red_onion|Red onions|produce|g|21|dry_store|kg|10kg sack|1000|1.10|
onion|Brown onions|produce|g|21|dry_store|kg|25kg sack|1000|0.85|
garlic|Garlic, peeled cloves|produce|g|14|walk_in|kg|1kg bag|1000|7.90|
potatoes|Potatoes, Maris Piper|produce|g|21|dry_store|kg|25kg sack|1000|0.62|
sweet_potato|Sweet potatoes|produce|g|14|dry_store|kg|10kg box|1000|1.90|
carrots|Carrots|produce|g|14|walk_in|kg|10kg sack|1000|0.75|
mushrooms|Chestnut mushrooms|produce|g|5|walk_in|kg|2.5kg punnet|1000|5.20|
red_pepper|Red peppers|produce|g|7|walk_in|kg|5kg box|1000|3.40|
avocado|Avocados, ripe|produce|each|4|walk_in|case|20 avocados|20|17.00|
lemon|Lemons|produce|each|14|walk_in|case|80 lemons|80|16.00|
lime|Limes|produce|each|14|walk_in|case|60 limes|60|12.00|
coriander|Coriander, fresh|produce|g|5|walk_in|kg||1000|12.00|
parsley|Flat-leaf parsley|produce|g|5|walk_in|kg||1000|11.00|
rocket|Wild rocket|produce|g|4|walk_in|kg|1kg bag|1000|9.40|
spinach|Baby spinach|produce|g|4|walk_in|kg|1kg bag|1000|7.20|
mixed_berries|Mixed berries|produce|g|4|walk_in|kg|2kg box|1000|9.80|
bananas|Bananas|produce|each|5|dry_store|case|100 bananas|100|14.00|
milk|Whole milk|dairy|ml|7|walk_in|l|2 x 2l|1000|0.95|
oat_milk|Oat milk, barista|dairy|ml|30|dry_store|l|6 x 1l|1000|1.65|
double_cream|Double cream|dairy|ml|10|walk_in|l|2l tub|1000|4.20|
butter|Unsalted butter|dairy|g|30|walk_in|kg|10 x 250g|1000|7.60|
cheddar|Mature cheddar|dairy|g|30|walk_in|kg|2.5kg block|1000|8.00|
american_cheese|American cheese slices|dairy|each|60|walk_in|pack|112 slices|112|11.20|
parmesan|Parmesan|dairy|g|60|walk_in|kg||1000|19.50|
mozzarella|Mozzarella, grated|dairy|g|21|walk_in|kg|2kg bag|1000|7.10|
halloumi|Halloumi|dairy|g|60|walk_in|kg|1kg block|1000|11.40|
greek_yoghurt|Greek yoghurt|dairy|g|14|walk_in|kg|1kg tub|1000|4.10|
vanilla_ice_cream|Vanilla ice cream|dairy|ml|180|freezer|l|5l tub|1000|3.10|
tortilla_wraps|Flour tortilla wraps 12in|bakery|each|30|dry_store|pack|18 wraps|18|5.04|
brioche_buns|Brioche burger buns|bakery|each|7|dry_store|pack|24 buns|24|9.60|
sourdough|Sourdough loaf, sliced|bakery|g|4|dry_store|each|800g loaf|800|3.20|
plain_flour|Plain flour|dry|g|180|dry_store|kg|16kg sack|1000|0.78|
pancake_mix|Buttermilk pancake mix|dry|g|180|dry_store|kg|3.5kg bag|1000|3.40|
panko|Panko breadcrumbs|dry|g|180|dry_store|kg|1kg bag|1000|4.60|
basmati_rice|Basmati rice|dry|g|365|dry_store|kg|10kg sack|1000|1.95|
arborio_rice|Arborio rice|dry|g|365|dry_store|kg|5kg bag|1000|2.80|
penne|Penne pasta|dry|g|365|dry_store|kg|3kg bag|1000|1.60|
rapeseed_oil|Rapeseed frying oil|dry|ml|180|dry_store|l|20l drum|1000|1.75|
olive_oil|Olive oil, extra virgin|dry|ml|365|dry_store|l|5l tin|1000|7.90|
chipotle_mayo|Chipotle mayonnaise|sauce|g|60|walk_in|kg|2.27kg tub|1000|4.60|
mayonnaise|Mayonnaise|sauce|g|90|dry_store|kg|5l tub|1000|3.10|
burger_sauce|Burger sauce|sauce|g|60|walk_in|kg|2.27kg tub|1000|4.20|
curry_paste|Tikka curry paste|sauce|g|180|dry_store|kg|2.2kg tub|1000|6.30|
maple_syrup|Maple syrup|sauce|ml|365|dry_store|l|1l bottle|1000|14.50|
baked_beans|Baked beans|dry|g|365|dry_store|kg|2.6kg tin|1000|1.35|
tinned_tomatoes|Chopped tomatoes|dry|g|365|dry_store|kg|2.5kg tin|1000|1.30|
pickles|Sliced gherkins|sauce|g|180|dry_store|kg|2.3kg jar|1000|3.60|
sugar|Caster sugar|dry|g|365|dry_store|kg|5kg bag|1000|1.15|
dark_chocolate|Dark chocolate callets|dry|g|365|dry_store|kg|2.5kg bag|1000|11.80|
frozen_fries|Skin-on fries, frozen|frozen|g|365|freezer|kg|4 x 2.5kg|1000|1.80|
sweet_potato_fries|Sweet potato fries, frozen|frozen|g|365|freezer|kg|4 x 2.5kg|1000|3.60|
hash_browns|Hash browns, frozen|frozen|each|365|freezer|case|100 pieces|100|9.00|
frozen_peas|Garden peas, frozen|frozen|g|365|freezer|kg|2.5kg bag|1000|1.70|
puff_pastry|Puff pastry sheets|frozen|g|180|freezer|kg|2kg box|1000|4.20|
onion_rings|Battered onion rings, frozen|frozen|g|365|freezer|kg|1kg bag|1000|3.20|
cola_can|Cola 330ml can|drinks|each|365|dry_store|case|24 cans|24|11.04|
lemonade_can|Lemonade 330ml can|drinks|each|365|dry_store|case|24 cans|24|9.36|
orange_juice|Orange juice, fresh|drinks|ml|10|walk_in|l|6 x 1l|1000|2.10|
lager_bottle|Lager 330ml bottle|drinks|each|365|dry_store|case|24 bottles|24|23.76|
red_wine|House red wine 75cl|drinks|ml|365|dry_store|case|6 x 75cl|750|5.90|
white_wine|House white wine 75cl|drinks|ml|365|dry_store|case|6 x 75cl|750|5.70|
coffee_beans|Espresso coffee beans|drinks|g|90|dry_store|kg|1kg bag|1000|16.50|
tea_bags|Breakfast tea bags|drinks|each|365|dry_store|box|1100 bags|1100|21.00|
sparkling_water|Sparkling water 750ml|drinks|each|365|dry_store|case|12 bottles|12|9.00|
"""


def _parse() -> dict[str, PantryItem]:
    items: dict[str, PantryItem] = {}
    for raw in _PANTRY.strip().splitlines():
        code, name, cat, base, shelf, area, pu, pack, bq, price, conv = [p.strip() for p in raw.split("|")]
        conversions = {}
        if conv:
            for part in conv.split(","):
                unit, factor = part.split("=")
                conversions[unit.strip()] = Decimal(factor)
        items[code] = PantryItem(code, name, cat, base, int(shelf), area, pu, pack or None, Decimal(bq),
                                 Decimal(price), conversions)
    return items


PANTRY: dict[str, PantryItem] = _parse()
