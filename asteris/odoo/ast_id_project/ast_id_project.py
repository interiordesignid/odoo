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

class sale_order_category_stage(models.Model):

    _name                   = "sale.order.category.stage"

    _order                  = "sequence asc"

    sequence                = fields.Integer('Sequence', related="project_task_type_id.sequence", store=True, required=False, readonly=True)
    project_task_type_id    = fields.Many2one('project.task.type', 'Stage', required=True, ondelete='cascade')
    so_category_id          = fields.Many2one('product.category', 'Category', required=True, ondelete='cascade')

class sale_order_category(models.Model):

    _name               = "sale.order.category"

    name                = fields.Char('Name', required=True)
    #stages              = fields.One2many('sale.order.category.stage', 'so_category_id', 'Project Stages')
    default_project_id  = fields.Many2one('project.project', required=True)
    default_stage_id    = fields.Many2one('project.task.type', string='Stage', domain="[('project_ids', '=', default_project_id)]", required=True)

class ast_id_project_default_configuration(models.Model):
    
    _name               = "project.default.configuration"

    default_project_id  = fields.Many2one('project.project', required=True)
    default_stage_id    = fields.Many2one('project.task.type', string='Stage', domain="[('project_ids', '=', default_project_id)]", required=True)
    
class ast_id_sale_order(models.Model):
    
    _name           = "sale.order"
    _inherit        = "sale.order"

    category_id     = fields.Many2one('sale.order.category', 'Category')
    project_task_id = fields.Many2one('project.task', 'Project Task')

    def action_create_project(self):
        for order in self:
            dummy, view_id = self.env['ir.model.data'].get_object_reference('ast_id_project', 'view_task_form_wizard')
            
            return {
                'name'          : "Project",
                'view_mode'     : 'form',
                'view_id'       : view_id,
                'view_type'     : 'form',
                'res_model'     : 'project.task',
                'type'          : 'ir.actions.act_window',
                'nodestroy'     : True,
                'target'        : 'current',
                'domain'        : '[]',
                'context': {
                    'default_name'          : self.name+" - "+self.partner_id.name,
                    'default_description'   : self.name+" - "+self.partner_id.name,
                    'default_stage_id'      : self.category_id.default_stage_id.id,
                    'default_project_id'    : self.category_id.default_project_id.id,
                    'default_sale_id'       : self.id,
                    'default_partner_id'    : self.partner_id.id
                }
            }

# class ast_id_project(models.Model):
    
#     _name           = "project.project"
#     _inherit        = "project.project"

#     sale_id         = fields.Many2one('sale.order', 'Order')

#     @api.model
#     def create(self, vals):
#         # Prevent double project creation
#         self = self.with_context(mail_create_nosubscribe=True)
#         project = super(ast_id_project, self).create(vals)
#         if not vals.get('subtask_project_id'):
#             project.subtask_project_id = project.id
#         if project.privacy_visibility == 'portal' and project.partner_id:
#             project.message_subscribe(project.partner_id.ids)
#         if project.sale_id:
#             project.sale_id.write({'project_id':project.id})
#         return project

class ast_id_project_task(models.Model):
    
    _name           = "project.task"
    _inherit        = "project.task"

    sale_id         = fields.Many2one('sale.order', 'Order')
    partner_id      = fields.Many2one('res.partner', 'Partner')

    @api.model
    def create(self, vals):
        # context: no_log, because subtype already handle this
        context = dict(self.env.context, mail_create_nolog=True)

        # for default stage
        if vals.get('project_id') and not context.get('default_project_id'):
            context['default_project_id'] = vals.get('project_id')
        # user_id change: update date_assign
        if vals.get('user_id'):
            vals['date_assign'] = fields.Datetime.now()
        # Stage change: Update date_end if folded stage
        if vals.get('stage_id'):
            vals.update(self.update_date_end(vals['stage_id']))
        task = super(ast_id_project_task, self.with_context(context)).create(vals)

        if task.sale_id:
            task.sale_id.write({'project_task_id':task.id})

        return task

    def create_task(self):
        for task in self:
            return task.action_subtask()

    # def name_get(self):
    #     result = []
    #     for project in self:
    #         name = project.name
    #         if project.sale_id:
    #             name = name + "(" + project.sale_id.name + "|" + project.sale_id.partner_id.name + ")"
    #         result.append((project.id, name))
    #     return result