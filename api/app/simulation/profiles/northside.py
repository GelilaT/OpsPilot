"""Northside Kitchens - two brunch & burger sites in Leeds and York with a different menu, suppliers and
thresholds (proves the platform is not built for one restaurant)."""

from datetime import time
from decimal import Decimal as D

from app.simulation.profile import DaypartShape, MenuSpec, OrgProfile, SiteSpec, StaffSpec, SupplierSpec, UserSpec
from app.simulation.profile import recipe as r

BRUNCH = ("lunch",)
ALL_DAY = ("lunch", "afternoon", "dinner", "late")
DAY = ("lunch", "afternoon")


def m(code, name, course, category, price, dayparts, pop, rec):
    return MenuSpec(code, name, course, category, D(price), dayparts, pop, r(rec))


MENU = (
    # Brunch (9)
    m("full_english", "The Full Northside", "main", "Brunch", "13.50", BRUNCH, 14,
      "pork_sausage 2each, bacon 60g, eggs 2each, black_pudding 40g, mushrooms 60g, tomato 60g, baked_beans 120g, "
      "hash_browns 1each, sourdough 60g, butter 10g"),
    m("veggie_breakfast", "Veggie breakfast", "main", "Brunch", "12.50", BRUNCH, 7,
      "halloumi 80g, eggs 2each, mushrooms 80g, spinach 40g, avocado 0.5each, baked_beans 120g, hash_browns 1each, "
      "sourdough 60g"),
    m("eggs_benedict", "Eggs Benedict", "main", "Brunch", "10.50", BRUNCH, 8,
      "eggs 2each, bacon 50g, sourdough 80g, butter 25g, lemon 0.1each, parsley 2g"),
    m("eggs_royale", "Eggs Royale", "main", "Brunch", "12.00", BRUNCH, 6,
      "eggs 2each, smoked_salmon 60g, sourdough 80g, butter 25g, lemon 0.1each"),
    m("avocado_toast", "Smashed avocado, poached egg", "main", "Brunch", "9.50", BRUNCH, 10,
      "avocado 0.75each@0.1, sourdough 90g, eggs 1each, lime 0.25each, coriander 3g"),
    m("pancake_stack", "Berry pancake stack", "main", "Brunch", "9.00", BRUNCH, 8,
      "pancake_mix 120g, milk 120ml, eggs 1each, maple_syrup 30ml, mixed_berries 50g, butter 10g"),
    m("bacon_pancakes", "Bacon & maple pancakes", "main", "Brunch", "10.00", BRUNCH, 7,
      "pancake_mix 120g, milk 120ml, eggs 1each, maple_syrup 30ml, bacon 60g"),
    m("breakfast_burrito", "Breakfast burrito", "main", "Brunch", "10.50", BRUNCH, 6,
      "tortilla_wraps 1each, eggs 2each, pork_sausage 1each, hash_browns 1each, cheddar 30g, red_pepper 30g, "
      "chipotle_mayo 20g"),
    m("yoghurt_bowl", "Greek yoghurt & berry bowl", "main", "Brunch", "7.50", BRUNCH, 4,
      "greek_yoghurt 200g, mixed_berries 60g, bananas 0.5each, maple_syrup 15ml"),
    # Burgers (9)
    m("classic_smash", "Classic smash burger", "main", "Burgers", "11.50", ALL_DAY, 14,
      "beef_patty 1each, brioche_buns 1each, american_cheese 2each, pickles 20g, onion 20g, burger_sauce 25g"),
    m("double_smash", "Double smash burger", "main", "Burgers", "14.50", ALL_DAY, 9,
      "beef_patty 2each, brioche_buns 1each, american_cheese 3each, pickles 20g, onion 20g, burger_sauce 30g"),
    m("bacon_cheese", "Bacon cheeseburger", "main", "Burgers", "13.50", ALL_DAY, 8,
      "beef_patty 1each, brioche_buns 1each, cheddar 30g, bacon 40g, burger_sauce 25g, cos_lettuce 20g, tomato 30g"),
    m("chipotle_burger", "Chipotle avocado burger", "main", "Burgers", "13.00", ALL_DAY, 5,
      "beef_patty 1each, brioche_buns 1each, chipotle_mayo 25g, red_onion 20g, cheddar 25g, avocado 0.25each"),
    m("fried_chicken_burger", "Fried chicken burger", "main", "Burgers", "12.50", ALL_DAY, 10,
      "chicken_thigh 170g, plain_flour 25g, rapeseed_oil 40ml, brioche_buns 1each, mayonnaise 25g, "
      "cos_lettuce 20g, pickles 15g"),
    m("chicken_halloumi", "Chicken & halloumi burger", "main", "Burgers", "13.00", ALL_DAY, 5,
      "chicken_breast 150g, halloumi 60g, brioche_buns 1each, mixed_leaves 20g, mayonnaise 20g"),
    m("halloumi_burger", "Halloumi & roast pepper burger", "main", "Burgers", "11.50", ALL_DAY, 4,
      "halloumi 140g, brioche_buns 1each, red_pepper 40g, rocket 15g, mayonnaise 20g"),
    m("mushroom_burger", "Mushroom & mozzarella burger", "main", "Burgers", "11.00", ALL_DAY, 3,
      "mushrooms 150g@0.05, mozzarella 40g, brioche_buns 1each, spinach 20g, garlic 4g, mayonnaise 20g"),
    m("fish_finger_sandwich", "Fish finger sandwich", "main", "Burgers", "11.00", ALL_DAY, 4,
      "cod_fillet 140g, panko 30g, eggs 0.5each, plain_flour 20g, sourdough 90g, mayonnaise 25g, lemon 0.25each"),
    # Plates (5)
    m("wings_basket", "Wings basket", "main", "Plates", "9.50", ALL_DAY, 6,
      "chicken_wings 300g, plain_flour 20g, rapeseed_oil 30ml, burger_sauce 25g"),
    m("loaded_fries", "Chilli loaded fries", "main", "Plates", "8.50", ALL_DAY, 5,
      "frozen_fries 250g, beef_mince 60g, cheddar 40g, bacon 30g, burger_sauce 25g, red_onion 10g"),
    m("chicken_tenders", "Chicken tenders", "main", "Plates", "9.00", ALL_DAY, 5,
      "chicken_breast 160g, panko 40g, eggs 0.5each, plain_flour 20g, rapeseed_oil 40ml, mayonnaise 20g"),
    m("caesar_wrap", "Chicken Caesar wrap", "main", "Plates", "10.00", ALL_DAY, 4,
      "chicken_breast 130g, tortilla_wraps 1each, cos_lettuce 60g, cheddar 15g, mayonnaise 25g"),
    m("mac_cheese", "Three-cheese mac", "main", "Plates", "9.00", ALL_DAY, 3,
      "plain_flour 15g, butter 15g, milk 150ml, cheddar 70g, mozzarella 30g, panko 15g"),
    # Sides (7)
    m("fries", "Fries", "side", "Sides", "3.50", ALL_DAY, 14, "frozen_fries 180g"),
    m("sweet_fries", "Sweet potato fries", "side", "Sides", "4.00", ALL_DAY, 7, "sweet_potato_fries 180g"),
    m("onion_rings", "Onion rings", "side", "Sides", "4.00", ALL_DAY, 6, "onion_rings 150g"),
    m("side_salad", "Side salad", "side", "Sides", "3.50", ALL_DAY, 3, "mixed_leaves 60g, tomato 40g, olive_oil 10ml"),
    m("wedges", "Potato wedges", "side", "Sides", "3.50", ALL_DAY, 4, "potatoes 250g@0.1, olive_oil 10ml"),
    m("garlic_mushrooms", "Garlic mushrooms", "side", "Sides", "3.50", ALL_DAY, 3,
      "mushrooms 100g@0.05, garlic 4g, butter 10g"),
    m("beans_side", "Side of beans", "side", "Sides", "2.50", BRUNCH, 3, "baked_beans 150g"),
    # Desserts & shakes (5)
    m("brownie", "Chocolate brownie", "dessert", "Desserts & shakes", "6.00", ALL_DAY, 6,
      "dark_chocolate 50g, butter 30g, sugar 40g, eggs 1each, plain_flour 20g, vanilla_ice_cream 70ml"),
    m("vanilla_shake", "Vanilla shake", "dessert", "Desserts & shakes", "5.50", ALL_DAY, 6,
      "vanilla_ice_cream 250ml, milk 150ml"),
    m("chocolate_shake", "Chocolate shake", "dessert", "Desserts & shakes", "5.80", ALL_DAY, 5,
      "vanilla_ice_cream 250ml, milk 150ml, dark_chocolate 25g"),
    m("banana_split", "Banana split", "dessert", "Desserts & shakes", "6.50", ALL_DAY, 3,
      "bananas 1each, vanilla_ice_cream 150ml, dark_chocolate 20g, double_cream 40ml"),
    m("eton_mess", "Eton mess", "dessert", "Desserts & shakes", "6.00", ALL_DAY, 3,
      "mixed_berries 80g@0.05, double_cream 70ml, sugar 25g, eggs 0.5each"),
    # Drinks (7)
    m("flat_white", "Flat white", "drink", "Drinks", "3.30", ALL_DAY, 12, "coffee_beans 18g, milk 150ml"),
    m("oat_latte", "Oat latte", "drink", "Drinks", "3.60", ALL_DAY, 6, "coffee_beans 18g, oat_milk 200ml"),
    m("tea", "Pot of tea", "drink", "Drinks", "2.50", ALL_DAY, 6, "tea_bags 1each, milk 30ml"),
    m("cola", "Cola", "drink", "Drinks", "3.00", ALL_DAY, 8, "cola_can 1each"),
    m("lemonade", "Lemonade", "drink", "Drinks", "3.00", ALL_DAY, 4, "lemonade_can 1each"),
    m("orange_juice", "Fresh orange juice", "drink", "Drinks", "3.25", ALL_DAY, 6, "orange_juice 250ml"),
    m("lager", "Lager, bottle", "drink", "Drinks", "5.00", ("afternoon", "dinner", "late"), 6, "lager_bottle 1each"),
)

INGREDIENTS = (
    # Kirkstall Butchers
    "beef_patty", "beef_mince", "chicken_thigh", "chicken_breast", "chicken_wings", "pork_sausage", "bacon",
    "black_pudding",
    # Dales Farm Eggs & Fish
    "eggs", "smoked_salmon", "cod_fillet",
    # Kirkgate Market Produce
    "cos_lettuce", "mixed_leaves", "tomato", "red_onion", "onion", "garlic", "potatoes", "mushrooms", "red_pepper",
    "avocado", "lemon", "lime", "coriander", "parsley", "spinach", "mixed_berries", "bananas", "rocket",
    # Wharfedale Dairy
    "milk", "oat_milk", "double_cream", "butter", "cheddar", "american_cheese", "mozzarella", "halloumi",
    "greek_yoghurt", "vanilla_ice_cream",
    # Aire Valley Foodservice
    "brioche_buns", "sourdough", "tortilla_wraps", "plain_flour", "pancake_mix", "panko", "rapeseed_oil",
    "olive_oil", "mayonnaise", "burger_sauce", "chipotle_mayo", "maple_syrup", "baked_beans", "pickles", "sugar",
    "dark_chocolate", "frozen_fries", "sweet_potato_fries", "hash_browns", "onion_rings",
    # Calder Drinks Wholesale
    "cola_can", "lemonade_can", "orange_juice", "lager_bottle", "coffee_beans", "tea_bags",
)


def staff(prefix: str, names: list[tuple[str, str, str, str]]) -> tuple[StaffSpec, ...]:
    return tuple(StaffSpec(f"{prefix}-{i}", n, role, D(rate), area) for i, (n, role, rate, area) in enumerate(names))


SUPPLIERS = (
    SupplierSpec("KIR", "Kirkstall Butchers", "GB561203384", "Abbey Road, Kirkstall, Leeds LS5 3HP",
                 "orders@kirkstallbutchers.example", "0113 555 0102", ("meat",), (0, 1, 2, 3, 4, 5), 1, 0.99,
                 "KB", price_factor=0.97),
    SupplierSpec("DFE", "Dales Farm Eggs & Fish", "GB602341170", "Dales Farm, Otley LS21 2DN",
                 "hello@dalesfarm.example", "01943 555 017", ("poultry", "fish"), (0, 2, 4, 5), 1, 0.975, "DF-",
                 alternatives={"chicken_breast": D("7.10"), "bacon": D("8.95")}),
    SupplierSpec("KMP", "Kirkgate Market Produce", "GB644781502", "Kirkgate Market, Leeds LS2 7HY",
                 "sales@kirkgateproduce.example", "0113 555 0131", ("produce",), (0, 1, 2, 3, 4, 5), 1, 0.98, "KMP"),
    SupplierSpec("WHD", "Wharfedale Dairy", "GB701445290", "Ilkley Road, Burley LS29 7DE",
                 "orders@wharfedaledairy.example", "01943 555 060", ("dairy",), (0, 2, 4, 5), 1, 0.995, "WD"),
    SupplierSpec("AVF", "Aire Valley Foodservice", "GB738120046", "Aire Valley Business Park, Bradford BD4 6RS",
                 "accounts@airevalley.example", "01274 555 090", ("bakery", "dry", "sauce", "frozen"), (1, 4), 2, 0.99,
                 "AVF-", price_factor=1.02,
                 alternatives={}),
    SupplierSpec("CDW", "Calder Drinks Wholesale", "GB790033128", "Calder Wharf, Wakefield WF1 5PW",
                 "trade@calderdrinks.example", "01924 555 044", ("drinks",), (2,), 1, 0.98, "CDW",
                 alternatives={"rapeseed_oil": D("1.72"), "sugar": D("1.12"), "plain_flour": D("0.83")},
                 zero_rated=False),
)

NORTHSIDE = OrgProfile(
    slug="northside-kitchens",
    name="Northside Kitchens",
    seed=2718,
    currency="GBP",
    timezone="Europe/London",
    region="england-and-wales",
    ingredients=INGREDIENTS,
    suppliers=SUPPLIERS,
    menu=MENU,
    sites=(
        SiteSpec(
            code="NK-LDS", name="Northside Kitchens - Leeds", city="leeds",
            address="41 Call Lane, Leeds LS1 7BT", latitude=D("53.7957"), longitude=D("-1.5418"), covers=110,
            orders_by_weekday=(150, 155, 165, 185, 240, 300, 260),
            dayparts=(
                DaypartShape("lunch", time(8, 30), time(15, 0), 0.56, time(11, 30)),
                DaypartShape("afternoon", time(15, 0), time(17, 0), 0.12, time(15, 45)),
                DaypartShape("dinner", time(17, 0), time(21, 0), 0.27, time(18, 45)),
                DaypartShape("late", time(21, 0), time(22, 0), 0.05, time(21, 15)),
            ),
            staff=staff("nk-l", [
                ("Ben C.", "head_chef", "16.80", "kitchen"), ("Grace N.", "sous_chef", "14.60", "kitchen"),
                ("Ollie F.", "line_cook", "12.40", "kitchen"), ("Maya P.", "line_cook", "12.40", "kitchen"),
                ("Zane Q.", "line_cook", "12.20", "kitchen"), ("Ivy G.", "kitchen_porter", "11.50", "kitchen"),
                ("Ravi D.", "general_manager", "17.50", "management"), ("Leah W.", "supervisor", "13.40", "management"),
                ("Finn H.", "server", "11.70", "floor"), ("Nina K.", "server", "11.70", "floor"),
                ("Omar S.", "server", "11.70", "floor"), ("Erin T.", "barista", "11.90", "floor"),
                ("Joel V.", "server", "11.60", "floor"), ("Sofia L.", "barista", "11.90", "floor"),
            ]),
            kitchen_staff_by_weekday=(5, 5, 5, 5, 6, 7, 6),
            floor_staff_by_weekday=(5, 5, 5, 6, 8, 10, 9),
            opening=time(8, 30), closing=time(22, 0),
        ),
        SiteSpec(
            code="NK-YRK", name="Northside Kitchens - York", city="york",
            address="7 Fossgate, York YO1 9TA", latitude=D("53.9590"), longitude=D("-1.0815"), covers=70,
            orders_by_weekday=(100, 100, 110, 125, 170, 230, 200),
            dayparts=(
                DaypartShape("lunch", time(8, 30), time(15, 0), 0.60, time(11, 45)),
                DaypartShape("afternoon", time(15, 0), time(17, 0), 0.13, time(15, 45)),
                DaypartShape("dinner", time(17, 0), time(21, 0), 0.23, time(18, 30)),
                DaypartShape("late", time(21, 0), time(22, 0), 0.04, time(21, 15)),
            ),
            staff=staff("nk-y", [
                ("Callum E.", "head_chef", "16.50", "kitchen"), ("Hana M.", "line_cook", "12.30", "kitchen"),
                ("Luca B.", "line_cook", "12.30", "kitchen"), ("Tess R.", "kitchen_porter", "11.50", "kitchen"),
                ("Amara O.", "general_manager", "17.20", "management"), ("Jack Y.", "server", "11.60", "floor"),
                ("Mia F.", "server", "11.60", "floor"), ("Noah J.", "barista", "11.80", "floor"),
                ("Isla P.", "server", "11.60", "floor"), ("Ethan W.", "server", "11.60", "floor"),
            ]),
            kitchen_staff_by_weekday=(3, 3, 3, 3, 4, 5, 5),
            floor_staff_by_weekday=(3, 3, 3, 4, 5, 7, 6),
            opening=time(8, 30), closing=time(22, 0),
        ),
    ),
    users=(
        UserSpec("owner@northside.example", "Jamal Adeyemi", "owner", None),
        UserSpec("gm.leeds@northside.example", "Ravi Desai", "general_manager", "NK-LDS"),
        UserSpec("gm.york@northside.example", "Amara Okafor", "general_manager", "NK-YRK"),
        UserSpec("chef.leeds@northside.example", "Ben Carter", "head_chef", "NK-LDS"),
        UserSpec("chef.york@northside.example", "Callum Evans", "head_chef", "NK-YRK"),
        UserSpec("shift.leeds@northside.example", "Leah Walsh", "shift_manager", "NK-LDS"),
    ),
    course_rates={
        "starter": {"lunch": 0.0, "afternoon": 0.0, "dinner": 0.0, "late": 0.0},
        "main": {"lunch": 0.95, "afternoon": 0.70, "dinner": 0.95, "late": 0.80},
        "side": {"lunch": 0.30, "afternoon": 0.35, "dinner": 0.55, "late": 0.50},
        "dessert": {"lunch": 0.10, "afternoon": 0.30, "dinner": 0.25, "late": 0.15},
        "drink": {"lunch": 1.30, "afternoon": 1.20, "dinner": 1.10, "late": 1.30},
    },
    covers_distribution={1: 0.22, 2: 0.42, 3: 0.14, 4: 0.16, 5: 0.04, 6: 0.02},
    channel_mix={"dine_in": 0.70, "takeaway": 0.15, "delivery": 0.15},
    discount_rate=0.07,
    void_rate=0.012,
    cash_share=0.10,
    config={
        "simulation.enabled": True,
        # Different thresholds and targets from The Copper Pot - configuration, not code.
        "invoice.price_increase_pct": 0.07,
        "targets.food_cost_pct": 0.28,
        "targets.labour_pct": 0.32,
        "targets.gp_pct": 0.70,
        "approval.invoice_limits": {"shift_manager": 0, "head_chef": 75000, "general_manager": 750000,
                                    "owner": None},
        "detection.severity_critical_minor": 20000,
        "menu.price_endings": [0, 50],
        "site.dayparts": [
            {"name": "lunch", "start": "08:30", "end": "15:00"},
            {"name": "afternoon", "start": "15:00", "end": "17:00"},
            {"name": "dinner", "start": "17:00", "end": "21:00"},
            {"name": "late", "start": "21:00", "end": "22:00"},
        ],
        "notifications.recipients": ["owner@northside.example"],
    },
)
