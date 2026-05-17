from odoo import models, fields

class HelpdeskTicketType(models.Model):
    _name = 'helpdesk.ticket.type'
    _description = 'Tipo de Ticket'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

#class HelpdeskTag(models.Model):
#    _inherit = 'helpdesk.tag'
#    related_ticket = fields.Many2one('helpdesk.ticket.type',string='Ticket relacionado')


