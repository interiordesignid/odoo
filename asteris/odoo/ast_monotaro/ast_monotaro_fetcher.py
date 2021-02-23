from openerp import models, fields as fields, api, _, exceptions
from dateutil.relativedelta import relativedelta
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import traceback
import re
import urllib.parse
import urllib.request
import base64
import time
import logging

_logger = logging.getLogger(__name__)

class ast_monotaro_fetcher(models.Model):
    
    _name           = "ast.monotaro.fetcher"
    
    @api.model
    def _default_datetime(self):
        return fields.Datetime.now()
    
    name                = fields.Char('Number', readonly=True, required=True, default="-")
    date                = fields.Datetime('Date', required=True, default=_default_datetime)
    categories          = fields.One2many('ast.monotaro.fetcher.category', 'fetch', 'Categories')
    fetched_categories  = fields.One2many('ast.monotaro.fetcher.category.fetched', 'fetch', 'Fetch Plan', readonly=True)
    records             = fields.One2many('ast.monotaro.fetcher.record', 'fetch', 'Data', readonly=True)
    debug_text          = fields.Text('Debug Text')
    state               = fields.Selection(
                            [('draft','Draft'),
                             ('ongoing','Ongoing'),
                             ('planned','Planned'),
                             ('fetched','Fetched'),
                             ('imported','Imported'),
                             ('cancelled','Cancelled'),
                            ], 'Status', readonly=True, required=True, size=32, default='draft')

    @api.model
    def create(self, values):
        sequence_pool = self.env['go.sequence']
        sequences = sequence_pool.search([('name','=','Monotaro Fetcher')])
        sequence = False
        if len(sequences) > 0:
            sequence = sequences[0]
        else:
            sequence = sequence_pool.create({'name':'Monotaro Fetcher','prefix':'MFT','suffix':False,'separator':'.'})
            
        values['name'] = sequence.generate_number(values['date'])
        
        return super(ast_monotaro_fetcher, self).create(values)

    def set_ongoing(self):
        self.write({'state':'ongoing'})

    def retry_fetch(self):
        for fetch in self:
            # query = '''
            #     DELETE FROM ast_monotaro_fetcher_record WHERE "fetch" = %s
            # '''
            # self.env.cr.execute(query,[fetch.id])
            query = '''
                UPDATE ast_monotaro_fetcher_category_fetched SET state = 'ongoing' WHERE "fetch" = %s AND state = 'failed'
            '''
            self.env.cr.execute(query,[fetch.id])

            fetch.write({'state':'planned'})

    def set_draft(self):
        for fetch in self:
            query = '''
                DELETE FROM ast_monotaro_fetcher_record WHERE "fetch" = %s
            '''
            self.env.cr.execute(query,[fetch.id])
            query = '''
                DELETE FROM ast_monotaro_fetcher_category_fetched WHERE "fetch" = %s
            '''
            self.env.cr.execute(query,[fetch.id])

            fetch.write({'state':'draft'})

    def cancel(self):
        for fetch in self:
            query = '''
                DELETE FROM ast_monotaro_fetcher_record WHERE "fetch" = %s
            '''
            self.env.cr.execute(query,[fetch.id])
            query = '''
                DELETE FROM ast_monotaro_fetcher_category_fetched WHERE "fetch" = %s
            '''
            self.env.cr.execute(query,[fetch.id])
            fetch.write({'state':'cancelled'})

    @api.model
    def fetch(self):
        line_model = self.env['ast.monotaro.fetcher.record']

        categories = {}
        categories_ = self.env['ast.monotaro.fetcher.record.category'].search([])
        for category in categories_:
            categories[category.code] = category.id

        brands = {}
        brands_ = self.env['ast.monotaro.fetcher.record.brand'].search([])
        for brand in brands_:
            brands[brand.name] = brand.id

        session = requests.Session()

        for fetch in self.env['ast.monotaro.fetcher'].search([('state','=','ongoing')]):
            inserted_skus = []
            for category in fetch.categories:
                self.recursive_category(fetch.id,session,inserted_skus,categories,brands,category.name)

            fetch.write({'state':'planned'})

    def recursive_category(self,fetch_id,session,inserted_skus,categories,brands,category):
        _logger.warning(category+" ===============================")
        category_model = self.env['ast.monotaro.fetcher.record.category']

        try:
            url = 'https://www.monotaro.id/corp_id/'+category+'.html'
            response = session.get(url)
            soup = BeautifulSoup(response.text,'lxml')
            category_name = soup.find("div", {"class": "top-category-desc"}).findChild().text
            exploded_category = category.split('/')
            category_code = exploded_category[len(exploded_category)-1]

            parent_id = False

            if len(exploded_category) > 2:
                parent_code = exploded_category[len(exploded_category)-2]
                if parent_code in categories:
                    parent_id = categories[parent_code]
                else:
                    parent_id = category_model.create({'name': parent_code, 'code': parent_code}).id
                    categories[parent_code] = parent_id

            if category_code not in categories:
                created_category = category_model.create({'name': category_name, 'code': category_code, 'parent':parent_id})
                categories[category_code] = created_category.id
                parent_id = created_category.id

            dd_kategori_element = soup.find("dd", {"class": "Kategori"})
            
            if dd_kategori_element:
                sub_categories = dd_kategori_element.findChild().findChildren(recursive=False)
                for sub_category_el in sub_categories:
                    sub_category_el = sub_category_el.findChild()

                    if sub_category_el and sub_category_el.name == 'a' and sub_category_el.has_attr('href') and sub_category_el['href'] != '#':
                        sub_category = sub_category_el['href'].split('.')
                        sub_category = sub_category[len(sub_category)-2]
                        sub_category = sub_category.replace('id/corp_id/','')

                        self.recursive_category(fetch_id,session,inserted_skus,categories,brands,sub_category)
            else:
                div_pages = soup.find("div", {"class": "pages"})
                number_of_page = 1
                if div_pages:
                    pages = div_pages.findChild().findChildren("li", {"class": "page-item"}, recursive=False)
                    last_page = pages[len(pages)-1].findChild()
                    number_of_page = int(last_page.text)

                self.env['ast.monotaro.fetcher.category.fetched'].create({'name':category, 'category': categories[category_code],'fetch':fetch_id, 'number_of_page': number_of_page})
                #self.fetch_item(fetch_id,session,inserted_skus,categories,brands,category_name,category_code,url,soup,category)

        except Exception:
            print(traceback.format_exc())

    @api.model
    def fetch_planned(self):
        session = requests.Session()
        inserted_skus = []

        brands = {}
        brands_ = self.env['ast.monotaro.fetcher.record.brand'].search([])
        for brand in brands_:
            brands[brand.name] = brand.id

        query = '''
            select id, sku from ast_monotaro_fetcher_record
        '''
        
        self.env.cr.execute(query,[])
        result = self.env.cr.fetchall()
        if len(result) > 0:
            for id, sku in result:
                inserted_skus.append(sku)

        for plan in self.env['ast.monotaro.fetcher.category.fetched'].search([('state','=','ongoing')]):
            try: 
                self.fetch_item(plan.fetch.id,plan.id,session,inserted_skus, brands, plan.name, plan.category.id, plan.number_of_page)
                plan.write({'state': 'fetched'})
                self.env.cr.commit()
                _logger.warning("Sleeping...")
                #time.sleep(600)
            except Exception:
                plan.write({'state': 'failed', 'error': traceback.format_exc()})

    def fetch_item(self, fetch_id, plan_id, session, inserted_skus, brands, category, category_id, number_of_page):

        base_url = 'https://www.monotaro.id/corp_id/'+category+'.html'
        
        for page in range(1,number_of_page+1):
            url = base_url + "?p=" + str(page)
            response = session.get(url)
            soup = BeautifulSoup(response.text,'lxml')
            products_grid = soup.find("ul", {"class": "products-grid"})
            if products_grid:
                product_as = products_grid.findChildren('li', {"class": "item-products"}, recursive=False)
                for products_a in product_as:
                    products_a = products_a.findChild().findChild().findChild('a')
                    
                    if products_a.has_attr('href') and products_a['href'] != '#':
                        product_url = products_a['href']
                        code = product_url.split('.')
                        code = code[len(code)-2]
                        code = code.split('/')
                        code = code[len(code)-1]

                        if code[0] == 's':
                            self.fetch_sku(fetch_id,plan_id,session,inserted_skus,category_id,brands,code,product_url)
                        elif code[0] == 'p':
                            response = session.get(product_url)
                            soup = BeautifulSoup(response.text,'lxml')

                            supertable = soup.find("table", {"id": "super-product-table"})

                            if supertable:
                                super_table = soup.find("table", {"id": "super-product-table"}).findChild('tbody')

                                for line in super_table.findChildren('tr'):
                                    sku_a = line.findChild('a')

                                    if sku_a.has_attr('href') and sku_a['href'] != '#':
                                        sku_url = sku_a['href']
                                        sku_code = sku_url.split('.')
                                        sku_code = sku_code[len(sku_code)-2]
                                        sku_code = sku_code.split('/')
                                        sku_code = sku_code[len(sku_code)-1].upper()

                                        if sku_code not in inserted_skus:
                                            self.fetch_sku(fetch_id,plan_id,session,inserted_skus,category_id,brands,sku_code,sku_url)

    def fetch_sku(self, fetch_id, plan_id, session, inserted_skus, category_id, brands, sku, url):
        response = session.get(url)
        soup = BeautifulSoup(response.text,'lxml')
        brand = soup.find("a", {"class": "brand-link"})
        brand_id = False
        brand_model = self.env['ast.monotaro.fetcher.record.brand']
        if brand:
            brand = brand.text.strip()
            if brand_id in brands:
                parent_id = brands[brand]
            else:
                created_brand = brand_model.create({'name': brand})
                brands[brand] = created_brand.id
                brand_id = created_brand.id

        product_name = soup.find("div", {"class": "product-name"})
        
        if product_name:
            product_name = soup.find("div", {"class": "product-name"}).findChild('h1').text.strip()
            product_sku = soup.find("span", {"class": "detail-content"}).text.strip()

            product_price = soup.find("span", {"class": "price"})
            if product_price:
                product_price = float((soup.find("span", {"class": "price"}).text).replace('.','').replace('Rp','').replace('Mulai ',''))
            else:
                product_price = 0.0
            zoom_a = soup.find("a", {"class": "cloud-zoom"})
            image_url = False

            if zoom_a and zoom_a.has_attr('href') and zoom_a['href'] != '#':
                image_url = zoom_a['href']

            attributes = soup.findAll("div", {"class": "content"})[0].findChild('span').findChildren('span')
            attributes_dict = {}
            odd = True
            key = ""
            for attribute in attributes:
                if odd:
                    key = attribute.text
                    odd = False
                else:
                    attributes_dict[key] = attribute.text
                    odd = True

            description = soup.findAll("div", {"class": "content"})[1].findChild('span')
            if description:
                description = description.text
            else:
                description = ""

            created_record = self.env['ast.monotaro.fetcher.record'].create({
                'name'          : product_name,
                'sku'           : product_sku,
                'category'      : category_id,
                'brand'         : brand_id,            
                'price'         : product_price,
                'pricevat'      : product_price/1.1,
                'image_url'     : image_url,
                'description'   : description,
                'fetch'         : fetch_id,
                'fetch_plan'    : plan_id,
            })

            for key, value in attributes_dict.items():
                self.env['ast.monotaro.fetcher.record.attribute'].create({'name': key, 'value': value, 'record': created_record.id})

            inserted_skus.append(product_sku)

            self.env.cr.commit()

            _logger.warning(product_name+" FETCHED")

    @api.model
    def fetch_image(self):
        for record in self.env['ast.monotaro.fetcher.record'].search([('image','=',False)],order='id ASC',limit=10):
            imagedata = urllib.request.urlopen(record.image_url)  
            image = base64.encodestring(imagedata.read())
            record.write({'image':image})
            print(record.name,"IMAGE FETCHED")

class ast_monotaro_fetcher_category(models.Model):
    
    _name           = "ast.monotaro.fetcher.category"
    
    name            = fields.Char('Name', required=True)
    fetch           = fields.Many2one('ast.monotaro.fetcher', 'Fetcher', required=True, ondelete="cascade")

class ast_monotaro_fetcher_record(models.Model):
    
    _name           = "ast.monotaro.fetcher.record"
    
    name            = fields.Char('Name', required=True)
    sku             = fields.Char('SKU')
    category        = fields.Many2one('ast.monotaro.fetcher.record.category', 'Category')
    brand           = fields.Many2one('ast.monotaro.fetcher.record.brand', 'Brand')
    attributes      = fields.One2many('ast.monotaro.fetcher.record.attribute', 'record', 'Attributes', readonly=True)
    price           = fields.Float('Price Without VAT')
    pricevat        = fields.Float('Price With VAT')
    image           = fields.Binary('Image')
    image_url       = fields.Char('Image URL')
    description     = fields.Text('Description')
    fetch           = fields.Many2one('ast.monotaro.fetcher', 'Fetcher', required=True, ondelete="cascade")
    fetch_plan      = fields.Many2one('ast.monotaro.fetcher.category.fetched', 'Fetch Plan')

class ast_monotaro_fetcher_record_brand(models.Model):
    
    _name           = "ast.monotaro.fetcher.record.brand"
    
    name            = fields.Char('Name', required=True)

class ast_monotaro_id_product_category(models.Model):

    _name           = "product.category"
    _inherit        = "product.category"

    fetch_id        = fields.Many2one('ast.monotaro.fetcher', 'Fetch')
    code            = fields.Char("Code")

class ast_monotaro_id_product(models.Model):
    
    _name           = "product.product"
    _inherit        = "product.product"

    fetch_id        = fields.Many2one('ast.monotaro.fetcher.record.category', 'Fetch')

class ast_monotaro_fetcher_record_category(models.Model):
    
    _name               = "ast.monotaro.fetcher.record.category"
    
    name                = fields.Char('Name', required=True)
    code                = fields.Char('Code', required=True)
    records             = fields.One2many('ast.monotaro.fetcher.record', 'category', 'Records', readonly=True)
    parent              = fields.Many2one('ast.monotaro.fetcher.record.category', 'Parent')
    import_to           = fields.Many2one('product.category', 'Target Category')
    imported_products   = fields.One2many('product.product', 'fetch_id', 'Records', readonly=True)
    state               = fields.Selection(
                        [
                            ('unimported','Unimported'),
                            ('imported','Imported'),
                        ], 'State', readonly=True, required=True, size=32, default='unimported')

    def action_pre_import_products(self):
        for order in self:
            dummy, view_id = self.env['ir.model.data'].get_object_reference('ast_monotaro', 'monotaro_import_form_wizard')
            
            return {
                'name'          : "Import By Category",
                'view_type'     : 'form',
                'view_mode'     : 'form',
                'view_id'       : view_id,
                'res_model'     : 'ast.monotaro.fetcher.record.category',
                'res_id'        : order.id,
                'type'          : 'ir.actions.act_window',
                'type'          : 'ir.actions.act_window',
                'target'        : 'new',
                'domain'        : '[]',
            }

    def import_products(self):
        product_brand_model = self.env['product.brand']
        product_category_model = self.env['product.category']
        product_model = self.env['product.product']
        product_attribute_model = self.env['product.product.attribute']
        last_category = False
        for category in self:
            print(category.id)
            max_back_travel = 10
            back_travel = 0
            current_category = category
            imported_product_category = False
            if not category.import_to:
                while back_travel < max_back_travel:
                    product_categories = product_category_model.search([('code','=',current_category.code)])
                    if len(product_categories) < 1:
                        product_category = product_category_model.create({'name':current_category.name,'code':current_category.code})
                        if last_category and not last_category.parent_id:
                            last_category.write({'parent_id':product_category.id})
                        last_category = product_category

                        if back_travel == 0:
                            imported_product_category = product_category
                    else:
                        if last_category and not last_category.parent_id:
                            last_category.write({'parent_id':product_categories[0].id})
                        last_category = product_categories[0]
                        if back_travel == 0:
                            imported_product_category = product_categories[0]

                    if current_category.parent:
                        current_category = current_category.parent
                        back_travel += 1
                    else:
                        break
            else:
                imported_product_category = category.import_to

            for record in category.records:
                brand = False
                if record.brand:
                    product_brands = product_brand_model.search([('name','=',record.brand.name)])
                    if len(product_brands) < 1:
                        brand = product_brand_model.create({'name':record.brand.name})
                    else:
                        brand = product_brands[0]

                imported_product = product_model.create({
                    'price'             : record.price,
                    'name'              : record.name,
                    'sku'               : record.sku,
                    'categ_id'          : imported_product_category.id if imported_product_category else False,
                    'brand_id'          : brand.id if brand else False,
                    'description_sale'  : record.description,
                    'fetch_id'          : category.id,
                })

                for attribute in record.attributes:
                    product_attribute_model.create({
                        'name'          : attribute.name,
                        'value'         : attribute.value,
                        'product_id'    : imported_product.id,
                    })

            category.write({'state':'imported'})

    def rollback_products(self):
        for category in self:
            category.imported_products.unlink()
            category.write({'state':'unimported'})

class ast_monotaro_fetcher_record_attribute(models.Model):
    
    _name           = "ast.monotaro.fetcher.record.attribute"
    
    name            = fields.Char('Name', required=True)
    value           = fields.Char('Value', required=True)
    record          = fields.Many2one('ast.monotaro.record', 'Record')

class ast_monotaro_fetcher_category_fetched(models.Model):
    
    _name           = "ast.monotaro.fetcher.category.fetched"
    
    name            = fields.Char('Name', required=True)
    fetch           = fields.Many2one('ast.monotaro.fetcher', 'Fetcher', required=True, ondelete="cascade")
    category        = fields.Many2one('ast.monotaro.fetcher.record.category', 'Category')
    number_of_page  = fields.Integer('Number of Page', required=True)
    error           = fields.Text('Error')
    state           = fields.Selection(
                        [('ongoing','Ongoing'),
                         ('fetched','Fetched'),
                         ('failed','Failed'),
                        ], 'Status', readonly=True, required=True, size=32, default='ongoing')
