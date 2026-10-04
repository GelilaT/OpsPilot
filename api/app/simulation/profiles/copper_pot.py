"""The Copper Pot - one 80-cover modern British kitchen & bar in Manchester (SRS Appendix C)."""

from datetime import time
from decimal import Decimal as D

from app.simulation.profile import DaypartShape, MenuSpec, OrgProfile, SiteSpec, StaffSpec, SupplierSpec, UserSpec
from app.simulation.profile import recipe as r

ALL_DAY = ("lunch", "afternoon", "dinner", "late")
MEALS = ("lunch", "dinner")
MEALS_LATE = ("lunch", "dinner", "late")
LIGHT = ("lunch", "afternoon", "dinner", "late")


def m(code, name, course, category, price, dayparts, pop, rec):
    return MenuSpec(code, name, course, category, D(price), dayparts, pop, r(rec))


MENU = (
    # Starters (7)
    m("tomato_soup", "Roast tomato soup, sourdough", "starter", "Starters", "6.50", MEALS, 5,
      "tinned_tomatoes 200g, onion 40g, garlic 5g, double_cream 20ml, olive_oil 10ml, sourdough 60g"),
    m("garlic_mushrooms", "Garlic mushrooms on toast", "starter", "Starters", "7.00", MEALS, 5,
      "mushrooms 120g@0.05, garlic 8g, butter 15g, double_cream 30ml, sourdough 60g"),
    m("salt_pepper_wings", "Salt & pepper chicken wings", "starter", "Starters", "7.50", MEALS_LATE, 8,
      "chicken_wings 250g, plain_flour 20g, rapeseed_oil 30ml, lime 0.25each, coriander 3g"),
    m("prawn_cocktail", "Prawn cocktail, avocado", "starter", "Starters", "8.50", MEALS, 4,
      "prawns 90g, cos_lettuce 40g, mayonnaise 30g, lemon 0.25each, avocado 0.25each, sourdough 40g"),
    m("halloumi_fries", "Halloumi fries, yoghurt dip", "starter", "Starters", "7.00", MEALS_LATE, 6,
      "halloumi 120g, plain_flour 15g, rapeseed_oil 30ml, greek_yoghurt 30g"),
    m("chicken_skewers", "Lemon chicken skewers", "starter", "Starters", "8.00", MEALS, 4,
      "chicken_breast 130g, greek_yoghurt 30g, lemon 0.25each, red_pepper 40g, olive_oil 10ml"),
    m("croquettes", "Cheddar & onion croquettes", "starter", "Starters", "6.50", MEALS, 3,
      "potatoes 120g@0.1, cheddar 30g, onion 20g, panko 20g, eggs 0.5each, rapeseed_oil 25ml"),
    # Mains (14) - four chicken thigh dishes (Appendix B)
    m("chicken_wrap", "Chicken Wrap", "main", "Mains", "9.50", ALL_DAY, 8.6,
      "chicken_thigh 200g, tortilla_wraps 1each, cos_lettuce 30g, tomato 40g, red_onion 20g, chipotle_mayo 28g, "
      "cheddar 30g, lime 0.25each, coriander 4g, frozen_fries 150g"),
    m("chicken_burger", "Buttermilk chicken burger", "main", "Mains", "13.50", ALL_DAY, 6.6,
      "chicken_thigh 180g, brioche_buns 1each, plain_flour 25g, rapeseed_oil 40ml, cos_lettuce 25g, "
      "mayonnaise 25g, frozen_fries 180g"),
    m("chicken_curry", "Chicken tikka curry, basmati", "main", "Mains", "14.00", MEALS_LATE, 5.9,
      "chicken_thigh 180g, curry_paste 40g, tinned_tomatoes 120g, onion 60g, double_cream 40ml, "
      "basmati_rice 90g, coriander 4g"),
    m("chicken_caesar", "Chicken Caesar salad", "main", "Mains", "12.50", ALL_DAY, 4.6,
      "chicken_thigh 160g, cos_lettuce 120g@0.1, parmesan 15g, sourdough 40g, mayonnaise 25g, olive_oil 10ml, "
      "lemon 0.25each"),
    m("beef_burger", "Copper Pot beef burger", "main", "Mains", "14.50", ALL_DAY, 12,
      "beef_mince 180g, brioche_buns 1each, cheddar 25g, bacon 30g, tomato 30g, cos_lettuce 20g, mayonnaise 20g, "
      "frozen_fries 180g"),
    m("steak_frites", "8oz sirloin, frites", "main", "Mains", "24.00", MEALS, 6,
      "beef_sirloin 230g, frozen_fries 200g, butter 15g, garlic 4g, mixed_leaves 30g"),
    m("fish_and_chips", "Beer-battered cod & chips", "main", "Mains", "15.50", MEALS_LATE, 12,
      "cod_fillet 180g, plain_flour 60g, rapeseed_oil 80ml, potatoes 300g@0.15, frozen_peas 80g, lemon 0.25each"),
    m("pork_belly", "Slow-roast pork belly", "main", "Mains", "17.50", MEALS, 5,
      "pork_belly 250g@0.05, potatoes 200g@0.1, carrots 80g@0.1, butter 15g, onion 40g"),
    m("bangers_mash", "Sausages & mash, onion gravy", "main", "Mains", "13.00", MEALS, 7,
      "pork_sausage 3each, potatoes 250g@0.1, butter 20g, milk 40ml, onion 60g, frozen_peas 60g"),
    m("lamb_shoulder", "Braised lamb shoulder", "main", "Mains", "19.50", MEALS, 4,
      "lamb_shoulder 250g@0.05, potatoes 200g@0.1, carrots 80g@0.1, garlic 6g, red_wine 50ml"),
    m("salmon_fillet", "Pan-roast salmon, crushed potatoes", "main", "Mains", "18.00", MEALS, 5,
      "salmon_fillet 170g, potatoes 180g@0.1, mixed_leaves 40g, butter 15g, lemon 0.25each"),
    m("duck_breast", "Duck breast, mash, berry jus", "main", "Mains", "21.00", MEALS, 3,
      "duck_breast 200g, potatoes 200g@0.1, butter 20g, mixed_berries 30g, red_wine 40ml"),
    m("mushroom_risotto", "Wild mushroom risotto", "main", "Mains", "13.50", MEALS, 4,
      "arborio_rice 100g, mushrooms 120g@0.05, parmesan 20g, butter 20g, onion 40g, white_wine 50ml, garlic 4g"),
    m("pepper_penne", "Roast pepper & mozzarella penne", "main", "Mains", "12.00", ALL_DAY, 4,
      "penne 120g, red_pepper 80g@0.1, tinned_tomatoes 120g, garlic 5g, olive_oil 15ml, mozzarella 40g"),
    # Sides (7)
    m("side_fries", "Skin-on fries", "side", "Sides", "3.75", ALL_DAY, 12, "frozen_fries 180g"),
    m("side_sweet_fries", "Sweet potato fries", "side", "Sides", "4.25", ALL_DAY, 6, "sweet_potato_fries 180g"),
    m("side_salad", "House salad", "side", "Sides", "3.75", ALL_DAY, 4,
      "mixed_leaves 60g, tomato 40g, red_onion 15g, olive_oil 10ml"),
    m("garlic_bread", "Garlic sourdough", "side", "Sides", "4.00", ALL_DAY, 6, "sourdough 90g, butter 20g, garlic 6g"),
    m("side_mash", "Buttery mash", "side", "Sides", "3.75", MEALS, 4, "potatoes 250g@0.1, butter 20g, milk 40ml"),
    m("buttered_peas", "Buttered peas", "side", "Sides", "3.50", MEALS, 2, "frozen_peas 120g, butter 10g"),
    m("mac_cheese", "Mac & cheese", "side", "Sides", "4.50", ALL_DAY, 5,
      "penne 90g, cheddar 50g, milk 100ml, butter 10g, plain_flour 10g"),
    # Desserts (6)
    m("sticky_toffee", "Sticky toffee pudding", "dessert", "Desserts", "7.00", MEALS, 9,
      "plain_flour 50g, sugar 60g, butter 40g, double_cream 50ml, eggs 1each"),
    m("brownie", "Chocolate brownie, ice cream", "dessert", "Desserts", "6.50", ALL_DAY, 8,
      "dark_chocolate 50g, butter 30g, sugar 40g, eggs 1each, plain_flour 20g, vanilla_ice_cream 70ml"),
    m("eton_mess", "Eton mess", "dessert", "Desserts", "6.50", MEALS, 4,
      "mixed_berries 80g@0.05, double_cream 70ml, sugar 25g, eggs 0.5each"),
    m("ice_cream_trio", "Ice cream trio", "dessert", "Desserts", "5.50", ALL_DAY, 4,
      "vanilla_ice_cream 180ml, mixed_berries 30g"),
    m("berry_crumble", "Berry crumble, cream", "dessert", "Desserts", "6.50", MEALS, 4,
      "mixed_berries 120g@0.05, plain_flour 40g, butter 30g, sugar 35g, double_cream 40ml"),
    m("cheeseboard", "Cheddar board, sourdough", "dessert", "Desserts", "8.50", MEALS_LATE, 2,
      "cheddar 60g, sourdough 60g, butter 10g"),
    # Drinks (8)
    m("cola", "Cola", "drink", "Drinks", "3.00", ALL_DAY, 10, "cola_can 1each"),
    m("lemonade", "Lemonade", "drink", "Drinks", "3.00", ALL_DAY, 5, "lemonade_can 1each"),
    m("orange_juice", "Fresh orange juice", "drink", "Drinks", "3.25", ALL_DAY, 4, "orange_juice 250ml"),
    m("lager", "Lager, bottle", "drink", "Drinks", "5.50", ALL_DAY, 12, "lager_bottle 1each"),
    m("red_wine_glass", "House red, 175ml", "drink", "Drinks", "7.00", ALL_DAY, 6, "red_wine 175ml"),
    m("white_wine_glass", "House white, 175ml", "drink", "Drinks", "7.00", ALL_DAY, 6, "white_wine 175ml"),
    m("flat_white", "Flat white", "drink", "Drinks", "3.40", ALL_DAY, 7, "coffee_beans 18g, milk 150ml"),
    m("sparkling_water", "Sparkling water 750ml", "drink", "Drinks", "3.50", ALL_DAY, 4, "sparkling_water 1each"),
)

INGREDIENTS = (
    # Ashworth Meats (Supplier A)
    "chicken_thigh", "chicken_breast", "chicken_wings", "beef_mince", "beef_sirloin", "pork_belly",
    "pork_sausage", "bacon", "lamb_shoulder",
    # Bramley Poultry & Fish (Supplier B)
    "duck_breast", "eggs", "cod_fillet", "salmon_fillet", "prawns",
    # Fresh Fields Produce
    "cos_lettuce", "mixed_leaves", "tomato", "red_onion", "onion", "garlic", "potatoes", "carrots", "mushrooms",
    "red_pepper", "avocado", "lemon", "lime", "coriander", "mixed_berries",
    # Peak Dale Dairy
    "milk", "double_cream", "butter", "cheddar", "parmesan", "mozzarella", "halloumi", "greek_yoghurt",
    "vanilla_ice_cream",
    # Castlefield Foodservice
    "tortilla_wraps", "brioche_buns", "sourdough", "plain_flour", "panko", "basmati_rice", "arborio_rice", "penne",
    "rapeseed_oil", "olive_oil", "chipotle_mayo", "mayonnaise", "curry_paste", "tinned_tomatoes", "sugar",
    "dark_chocolate", "frozen_fries", "sweet_potato_fries", "frozen_peas",
    # Northgate Cash & Carry (drinks)
    "cola_can", "lemonade_can", "orange_juice", "lager_bottle", "red_wine", "white_wine", "coffee_beans",
    "sparkling_water",
)

SUPPLIERS = (
    SupplierSpec("ASH", "Ashworth Meats Ltd", "GB284551237", "Unit 4, Brindle Way, Salford M50 2QP",
                 "orders@ashworthmeats.example", "0161 555 0141", ("meat",), (0, 1, 2, 3, 4, 5), 1, 0.995,
                 "AM-", aliases=("Ashworth Meats", "Ashworth Meat Co")),
    SupplierSpec("BRM", "Bramley Poultry & Fish Ltd", "GB319004528", "Bramley Farm, Stockport SK7 1LD",
                 "sales@bramleypoultry.example", "0161 555 0188", ("poultry", "fish"), (0, 1, 2, 3, 4, 5), 1, 0.97,
                 "BPF-", alternatives={"chicken_thigh": D("7.19"), "chicken_breast": D("7.55")},
                 aliases=("Bramley Poultry",)),
    SupplierSpec("FFP", "Fresh Fields Produce", "GB402118853", "Smithfield Market, Manchester M4 6BF",
                 "accounts@freshfields.example", "0161 555 0110", ("produce",), (0, 1, 2, 3, 4, 5), 1, 0.985,
                 "FF-"),
    SupplierSpec("CFS", "Castlefield Foodservice", "GB118846210", "Castlefield Trading Estate, Manchester M15 4LZ",
                 "invoices@castlefield.example", "0161 555 0177",
                 ("bakery", "dry", "sauce", "frozen"), (1, 4), 2, 0.99, "CFS",
                 aliases=("Castlefield Food Service",)),
    SupplierSpec("PKD", "Peak Dale Dairy", "GB220954061", "Peak Dale, Buxton SK17 8AX",
                 "orders@peakdaledairy.example", "01298 555 012", ("dairy",), (0, 2, 4), 1, 0.995, "PD-"),
    SupplierSpec("NCC", "Northgate Cash & Carry", "GB377102914", "Northgate Road, Oldham OL1 3AN",
                 "trade@northgatecc.example", "0161 555 0199", ("drinks",), (1,), 1, 0.98, "NG-",
                 alternatives={"rapeseed_oil": D("1.69"), "plain_flour": D("0.81"), "sugar": D("1.09"),
                               "frozen_fries": D("1.86")},
                 zero_rated=False),
)

STAFF = (
    StaffSpec("cp-k1", "Marcus B.", "head_chef", D("17.50"), "kitchen"),
    StaffSpec("cp-k2", "Aisha K.", "sous_chef", D("15.00"), "kitchen"),
    StaffSpec("cp-k3", "Tom W.", "chef_de_partie", D("13.20"), "kitchen"),
    StaffSpec("cp-k4", "Priya S.", "chef_de_partie", D("12.80"), "kitchen"),
    StaffSpec("cp-k5", "Lewis D.", "kitchen_porter", D("11.60"), "kitchen"),
    StaffSpec("cp-k6", "Jan P.", "kitchen_porter", D("11.60"), "kitchen"),
    StaffSpec("cp-m1", "Hannah R.", "general_manager", D("18.00"), "management"),
    StaffSpec("cp-m2", "Dan O.", "assistant_manager", D("14.00"), "management"),
    StaffSpec("cp-f1", "Chloe M.", "server", D("11.80"), "floor"),
    StaffSpec("cp-f2", "Sam T.", "server", D("11.80"), "floor"),
    StaffSpec("cp-f3", "Ruby L.", "server", D("11.80"), "floor"),
    StaffSpec("cp-f4", "Kofi A.", "server", D("11.80"), "floor"),
    StaffSpec("cp-f5", "Ella J.", "server", D("11.60"), "floor"),
    StaffSpec("cp-f6", "Josh H.", "bartender", D("12.20"), "floor"),
)

COPPER_POT = OrgProfile(
    slug="copper-pot",
    name="The Copper Pot",
    seed=4471,
    currency="GBP",
    timezone="Europe/London",
    region="england-and-wales",
    ingredients=INGREDIENTS,
    suppliers=SUPPLIERS,
    menu=MENU,
    sites=(
        SiteSpec(
            code="CP1", name="The Copper Pot - Manchester", city="manchester",
            address="12 Deansgate, Manchester M3 2BW", latitude=D("53.4808"), longitude=D("-2.2426"), covers=80,
            orders_by_weekday=(110, 115, 125, 140, 226, 240, 175),
            dayparts=(
                DaypartShape("lunch", time(11, 30), time(15, 0), 0.30, time(12, 50)),
                DaypartShape("afternoon", time(15, 0), time(17, 0), 0.10, time(16, 0)),
                DaypartShape("dinner", time(17, 0), time(21, 30), 0.53, time(19, 15)),
                DaypartShape("late", time(21, 30), time(23, 0), 0.07, time(21, 45)),
            ),
            staff=STAFF,
            kitchen_staff_by_weekday=(5, 5, 5, 6, 8, 8, 6),
            floor_staff_by_weekday=(6, 6, 6, 7, 10, 11, 8),
            opening=time(11, 30), closing=time(23, 0),
        ),
    ),
    users=(
        UserSpec("owner@copperpot.example", "Olivia Bennett", "owner", None),
        UserSpec("gm@copperpot.example", "Hannah Reid", "general_manager", "CP1"),
        UserSpec("chef@copperpot.example", "Marcus Brown", "head_chef", "CP1"),
        UserSpec("shift@copperpot.example", "Dan Okoro", "shift_manager", "CP1"),
    ),
    course_rates={
        "starter": {"lunch": 0.12, "afternoon": 0.05, "dinner": 0.30, "late": 0.20},
        "main": {"lunch": 0.92, "afternoon": 0.55, "dinner": 0.95, "late": 0.60},
        "side": {"lunch": 0.25, "afternoon": 0.25, "dinner": 0.30, "late": 0.35},
        "dessert": {"lunch": 0.12, "afternoon": 0.20, "dinner": 0.28, "late": 0.10},
        "drink": {"lunch": 1.00, "afternoon": 1.10, "dinner": 1.40, "late": 1.70},
    },
    covers_distribution={1: 0.25, 2: 0.40, 3: 0.15, 4: 0.15, 5: 0.03, 6: 0.02},
    channel_mix={"dine_in": 0.78, "takeaway": 0.12, "delivery": 0.10},
    discount_rate=0.05,
    void_rate=0.015,
    cash_share=0.15,
    config={
        "simulation.enabled": True,
        "targets.food_cost_pct": 0.30,
        "targets.labour_pct": 0.30,
        "targets.gp_pct": 0.65,
        "notifications.recipients": ["owner@copperpot.example", "gm@copperpot.example"],
    },
    # Appendix B arithmetic is exact: the wrap's other ingredients do not drift in price.
    stable_price_ingredients=frozenset({
        "chicken_thigh", "tortilla_wraps", "cos_lettuce", "tomato", "red_onion", "chipotle_mayo", "cheddar",
        "lime", "coriander", "frozen_fries",
    }),
    par_levels={"chicken_thigh": D(15000)},  # raised to 18 kg after the 19 Sep short delivery (S7)
)
