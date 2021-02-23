from odoo import api, fields, models, _, exceptions
from datetime import datetime, timedelta, date
from dateutil import relativedelta
import copy

class go_sequence(models.Model):
    
    _name           = "go.sequence"
    _order          = "name"
    
    name            = fields.Char('Nama', required=True)
    prefix          = fields.Char('Awalan')
    suffix          = fields.Char('Akhiran')
    separator       = fields.Char('Pemisah', required=True)
    digit           = fields.Integer('Digit',required=True, default=5)
    lines           = fields.One2many('go.sequence.line','sequence','Sequence')
    
    def generate_number(self, date):
        request_date = False
        if len(date) > 10:    
            request_date = datetime.strptime(date,'%Y-%m-%d %H:%M:%S')
        else:
            request_date = datetime.strptime(date,'%Y-%m-%d')
        sequence_line_model = self.env['go.sequence.line']
        existing_sequence_lines = sequence_line_model.search([('sequence','=',self.id),('month','=',request_date.month),('year','=',request_date.year)])        
        if len(existing_sequence_lines) > 0:
            sequence_line = existing_sequence_lines[0]
        else:
            sequence_line = sequence_line_model.create({'sequence':self.id,'month':request_date.month, 'year':request_date.year})        
        return sequence_line.generate_number()
    
    def generate_number_without_date(self):
        sequence_line_model = self.env['go.sequence.line']
        existing_sequence_lines = sequence_line_model.search([('sequence','=',self.id),('month','=',0),('year','=',0)])        
        if len(existing_sequence_lines) > 0:
            sequence_line = existing_sequence_lines[0]
        else:
            sequence_line = sequence_line_model.create({'sequence':self.id,'month':0, 'year':0})        
        return sequence_line.generate_number_without_date()

class go_seqence_line(models.Model):
    
    _name           = "go.sequence.line"
    _order          = "sequence,year,month"
    
    sequence                = fields.Many2one('go.sequence', 'Kategori Deposit')
    month                   = fields.Integer('Bulan', required=True)
    year                    = fields.Integer('Tahun', required=True)
    last_sequence_number    = fields.Integer('Nomor Terakhir', required=True, default=0)
    
    def generate_number(self):
        number = ""
        if self.sequence.prefix:
            number += self.sequence.prefix+self.sequence.separator
        number += str(self.year)+self.sequence.separator
        number += str(self.month).zfill(2)+self.sequence.separator
        number += str(self.last_sequence_number+1).zfill(self.sequence.digit)
        if self.sequence.suffix:
            number += self.sequence.separator+str(self.suffix)
        self.write({'last_sequence_number':self.last_sequence_number+1})
        return number
    
    def generate_number_without_date(self):
        number = ""
        if self.sequence.prefix:
            number += self.sequence.prefix+self.sequence.separator
        number += str(self.last_sequence_number+1).zfill(self.sequence.digit)
        if self.sequence.suffix:
            number += self.sequence.separator+str(self.suffix)
        self.write({'last_sequence_number':self.last_sequence_number+1})
        return number
            
    _sql_constraints = [
        ('sequence_uniq', 'unique(sequence,month,year)', 'Kombinasi bulan dan tahun sudah terdaftar!'),
    ]