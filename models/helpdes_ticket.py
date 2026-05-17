from odoo import models, fields

class HelpdeskTicketType(models.Model):
    _name = 'helpdesk.ticket.type'
    _description = 'Helpdesk Ticket Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

class HelpdeskTag(models.Model):
    _inherit = 'helpdesk.tag'
    related_ticket = fields.Many2one('helpdesk.ticket.type',string='Ticket relacionado')


class HelpdeskTicketType(models.Model):
    _name = 'helpdesk.ticket.type'
    _description = 'Tipo de Ticket'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)