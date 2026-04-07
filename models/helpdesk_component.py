from odoo import models, fields, api


class HelpdeskTicketComponent(models.Model):
    _name = 'helpdesk.ticket.component'
    _description = 'Componentes usados en Ticket'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket',
        string='Ticket',
        ondelete='cascade',
        required=True
    )
    suitable_component_ids = fields.Many2many(
        related="helpdesk_ticket_id.suitable_component_ids"
    )
    product_id = fields.Many2one(
        'product.product',
        string='Componente',
        required=True,
        domain="[('id', 'in', suitable_component_ids)]",
    )

    description = fields.Char(
        string='Descripción'
    )

    cost = fields.Float(
        string='Costo',
        store=True,
    )

    quantity = fields.Float(
        string='Cantidad',
        default=1.0
    )

    value = fields.Float(
        string='Valor',
        compute="_compute_value",
        store=True
    )
    subtotal_cost = fields.Float(
        string="Costo Total",
        compute="_compute_subtotal_cost",
        store=True
    )
    
    subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True
    )
    
    @api.depends('cost')
    def _compute_value(self):
        for line in self:
            line.value = line.cost * 3.5

    @api.depends('value', 'quantity')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.value * line.quantity

    @api.depends('cost', 'quantity')
    def _compute_subtotal_cost(self):
        for line in self:
            line.subtotal_cost = line.cost * line.quantity

    @api.onchange('product_id')
    def _onchange_product(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.display_name
                line.cost = line.product_id.standard_price