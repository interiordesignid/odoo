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
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# 1.  SKU [DONE]
# 2.  Brand [DONE]
# User will be able to assign brands
# 3.  Custom Attributes [DONE]
# For each product category, user will be able to define certain attributes that can be filled in the product form. These attributes must also be searchable.
# 4.  Variant
# For each variant, the user will be able to define a 
# description [DONE], upload photos [DONE] and 3D models [DONE].
# 5.  Keyword
# Keyword can be added and be used for search / auto-complete purposes

class ast_id_product_category_attribute(models.Model):

    _name               = "product.category.attribute"

    attribute           = fields.Many2one('product.attribute', required=True)
    product_category_id = fields.Many2one('product.category', 'Category', ondelete='cascade')

class ast_id_product_category(models.Model):

    _name           = "product.category"
    _inherit        = "product.category"

    attributes = fields.One2many('product.category.attribute', 'product_category_id', 'Default Attributes')

class ast_id_product_template(models.Model):
    _name = "product.template"
    _inherit = "product.template"

    @api.onchange('categ_id')
    def onchange_categ_id(self):
        new_attribute_lines = []
        for attribute in self.categ_id.attributes:
            new_attribute_lines.append((0,0,{
                'attribute_id'  : attribute.attribute.id,
            }))
        self.attribute_line_ids = new_attribute_lines

class ast_id_product_brand(models.Model):

    _name               = "product.brand"

    name                = fields.Char('Name', required=True)

class ast_id_product_product_attribute(models.Model):

    _name               = "product.product.attribute"

    name                = fields.Char('Name', required=True)
    value               = fields.Char('Value')
    product_id          = fields.Many2one('product.product', 'Product', ondelete='cascade')

class ast_id_product_3d_model(models.Model):
    
    _name               = "product.3d.model"

    name                = fields.Char('Name', required=True)
    model               = fields.Binary('Model')
    model_name          = fields.Char('Model Name')
    product_id          = fields.Many2one('product.product', 'Product', ondelete='cascade')

class ast_id_product(models.Model):
    
    _name           = "product.product"
    _inherit        = "product.product"

    @api.depends('attributes')
    def _compute_search_attributes(self):
        self.search_attributes = ""
        for attribute in self.attributes:
            self.search_attributes += attribute.name+":"+attribute.value

    sku                 = fields.Char('SKU')
    brand_id            = fields.Many2one('product.brand', 'Brand')
    attributes          = fields.One2many('product.product.attribute', 'product_id', 'Attributes')
    search_attributes   = fields.Char('Search Attributes',compute='_compute_search_attributes',store=True)
    three_d_models      = fields.One2many('product.3d.model', 'product_id', '3D Models')
    description         = fields.Text('Description')
    
    @api.onchange('categ_id')
    def onchange_categ_id(self):
        new_attributes = []
        for attribute in self.categ_id.attributes:
            new_attributes.append((0,0,{
                    'name'  : attribute.name,
                    'value' : "",
                }))
        self.attributes = new_attributes

    def name_get(self):
        # TDE: this could be cleaned a bit I think

        def _name_get(d):
            name = d.get('name', '')
            code = self._context.get('display_default_code', True) and d.get('default_code', False) or False
            if code:
                name = '[%s] %s' % (code,name)
            return (d['id'], name)

        partner_id = self._context.get('partner_id')
        if partner_id:
            partner_ids = [partner_id, self.env['res.partner'].browse(partner_id).commercial_partner_id.id]
        else:
            partner_ids = []
        company_id = self.env.context.get('company_id')

        # all user don't have access to seller and partner
        # check access and use superuser
        self.check_access_rights("read")
        self.check_access_rule("read")

        result = []

        # Prefetch the fields used by the `name_get`, so `browse` doesn't fetch other fields
        # Use `load=False` to not call `name_get` for the `product_tmpl_id`
        self.sudo().read(['name', 'default_code', 'product_tmpl_id'], load=False)

        product_template_ids = self.sudo().mapped('product_tmpl_id').ids

        if partner_ids:
            supplier_info = self.env['product.supplierinfo'].sudo().search([
                ('product_tmpl_id', 'in', product_template_ids),
                ('name', 'in', partner_ids),
            ])
            # Prefetch the fields used by the `name_get`, so `browse` doesn't fetch other fields
            # Use `load=False` to not call `name_get` for the `product_tmpl_id` and `product_id`
            supplier_info.sudo().read(['product_tmpl_id', 'product_id', 'product_name', 'product_code'], load=False)
            supplier_info_by_template = {}
            for r in supplier_info:
                supplier_info_by_template.setdefault(r.product_tmpl_id, []).append(r)
        for product in self.sudo():
            variant = product.product_template_attribute_value_ids._get_combination_name()

            name = variant and "%s (%s)" % (product.name, variant) or product.name
            sellers = []
            if partner_ids:
                product_supplier_info = supplier_info_by_template.get(product.product_tmpl_id, [])
                sellers = [x for x in product_supplier_info if x.product_id and x.product_id == product]
                if not sellers:
                    sellers = [x for x in product_supplier_info if not x.product_id]
                # Filter out sellers based on the company. This is done afterwards for a better
                # code readability. At this point, only a few sellers should remain, so it should
                # not be a performance issue.
                if company_id:
                    sellers = [x for x in sellers if x.company_id.id in [company_id, False]]
            if sellers:
                for s in sellers:
                    seller_variant = s.product_name and (
                        variant and "%s (%s)" % (s.product_name, variant) or s.product_name
                        ) or False
                    mydict = {
                              'id': product.id,
                              'name': seller_variant or name,
                              'default_code': s.product_code or product.default_code,
                              }
                    temp = _name_get(mydict)
                    if temp not in result:
                        result.append(temp)
            else:
                mydict = {
                          'id': product.id,
                          'name': name,
                          'default_code': product.default_code,
                          }
                result.append(_name_get(mydict))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        if not args:
            args = []
        if name:
            positive_operators = ['=', 'ilike', '=ilike', 'like', '=like']
            product_ids = []
            if operator in positive_operators:
                product_ids = self._search([('default_code', '=', name)] + args, limit=limit, access_rights_uid=name_get_uid)
                if not product_ids:
                    product_ids = self._search([('barcode', '=', name)] + args, limit=limit, access_rights_uid=name_get_uid)
            if not product_ids and operator not in expression.NEGATIVE_TERM_OPERATORS:
                # Do not merge the 2 next lines into one single search, SQL search performance would be abysmal
                # on a database with thousands of matching products, due to the huge merge+unique needed for the
                # OR operator (and given the fact that the 'name' lookup results come from the ir.translation table
                # Performing a quick memory merge of ids in Python will give much better performance
                product_ids = self._search(args + [('default_code', operator, name)], limit=limit)
                if not limit or len(product_ids) < limit:
                    # we may underrun the limit because of dupes in the results, that's fine
                    limit2 = (limit - len(product_ids)) if limit else False
                    product2_ids = self._search(args + [('name', operator, name), ('id', 'not in', product_ids)], limit=limit2, access_rights_uid=name_get_uid)
                    product_ids.extend(product2_ids)
            elif not product_ids and operator in expression.NEGATIVE_TERM_OPERATORS:
                domain = expression.OR([
                    ['&', ('default_code', operator, name), ('name', operator, name)],
                    ['&', ('default_code', '=', False), ('name', operator, name)],
                ])
                domain = expression.AND([args, domain])
                product_ids = self._search(domain, limit=limit, access_rights_uid=name_get_uid)
            if not product_ids and operator in positive_operators:
                ptrn = re.compile('(\[(.*?)\])')
                res = ptrn.search(name)
                if res:
                    product_ids = self._search([('default_code', '=', res.group(2))] + args, limit=limit, access_rights_uid=name_get_uid)
            # still no results, partner in context: search on supplier info as last hope to find something
            if not product_ids and self._context.get('partner_id'):
                suppliers_ids = self.env['product.supplierinfo']._search([
                    ('name', '=', self._context.get('partner_id')),
                    '|',
                    ('product_code', operator, name),
                    ('product_name', operator, name)], access_rights_uid=name_get_uid)
                if suppliers_ids:
                    product_ids = self._search([('product_tmpl_id.seller_ids', 'in', suppliers_ids)], limit=limit, access_rights_uid=name_get_uid)
            # still no results, last attempt
           # if not products:
            #    query = '''
             #       SELECT product_id FROM product_product_attribute WHERE LOWER(value) LIKE LOWER(%s)
            #    '''
             #   self._cr.execute(query, ("%"+name+"%",))
              #  result = self.env.cr.fetchall()
            #    if len(result) > 0:
             #       products = self.search([('id', 'in', result[0])] + args, limit=limit)
        else:
            product_ids = self._search(args, limit=limit, access_rights_uid=name_get_uid)
        return models.lazy_name_get(self.browse(product_ids).with_user(name_get_uid))