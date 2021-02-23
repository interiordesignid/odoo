{
    'name': 'Monotaro.id Fetcher',
    'category': 'Tools',
    'summary': 'Monotaro.id Product Data Fetcher',
    'description': """
This module gives you the ability to crawl and fetch all data from monotaro.id website
""",
	"author" : "PT. Asteris Digital Lab",
    "website" : "https://asteris.id",
    'depends': ['base','go_sequence','product','ast_id_product','product'],
    'data': [
        'ast_monotaro_menu.xml',
        'ast_monotaro_fetcher.xml',
    ],
    'application': True,
}
