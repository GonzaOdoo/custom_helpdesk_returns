# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools.translate import _
from odoo.exceptions import UserError


class AccountMoveReversal(models.TransientModel):
    """
    Account move reversal wizard, it cancel an account move by reversing it.
    """
    _inherit = 'account.move.reversal'

    @api.constrains('journal_id', 'move_ids')
    def _check_journal_type(self):
        for record in self:
            # Solo validar si hay move_ids
            if record.move_ids:
                if record.journal_id.type not in record.move_ids.journal_id.mapped('type'):
                    raise UserError(_('Journal should be the same type as the reversed entry.'))


    
    def create_custom_refund(self, quantity=1, price_unit=None, reason=''):
        """
        Crea una nota de crédito personalizada con un solo producto.
        :param product_id: registro del producto (product.product o product.template)
        :param quantity: cantidad (por defecto 1)
        :param price_unit: precio unitario (opcional, si no se usa el de la lista de precios)
        :param reason: motivo de la nota de crédito
        """
        self.ensure_one()

        if not self.product_id:
            raise UserError('Por favor elija el producto a reembolsar')
        # Determinar el partner (cliente/proveedor)
        #partner = self.partner_id or (self.move_ids and self.move_ids[0].partner_id) or self.env['res.partner']
        partner = self.helpdesk_ticket_id.partner_id
        company = self.company_id or (self.move_ids and self.move_ids[0].company_id) or self.env.company
    
        # Tipo de nota: si es cliente -> out_refund, si es proveedor -> in_refund
        move_type = 'out_refund'  # ajusta según tu caso
        product_id = self.product_id
        # Obtener cuenta contable del producto
        account = product_id.product_tmpl_id.get_product_accounts()['income']
        if not account:
            account = self.env['account.account'].search([
                ('account_type', '=', 'income'),
                ('company_id', '=', company.id)
            ], limit=1)
            if not account:
                raise UserError(_("No se encontró una cuenta de ingresos para el producto %s.") % product_id.display_name)
    
        # Precio unitario
        if price_unit is None:
            price_unit = product_id.lst_price
    
        # Crear línea de factura
        line_vals = {
            'name': product_id.name,
            'product_id': product_id.id,
            'quantity': quantity,
            'price_unit': price_unit,
            'account_id': account.id,
            'tax_ids': [(6, 0, product_id.taxes_id.filtered(lambda t: t.company_id == company).ids)],
        }
    
        # Crear el asiento (nota de crédito)
        refund_vals = {
            'move_type': move_type,
            'partner_id': partner.id,
            'journal_id': self.journal_id.id or self.env['account.journal'].search([
                ('type', '=', 'sale' if move_type == 'out_refund' else 'purchase'),
                ('company_id', '=', company.id)
            ], limit=1).id,
            'invoice_date': fields.Date.context_today(self),
            'ref': reason or _('Nota de crédito personalizada'),
            'invoice_line_ids': [(0, 0, line_vals)],
            'company_id': company.id,
        }
    
        refund = self.env['account.move'].create(refund_vals)
        
        # Vincular al ticket de helpdesk si aplica
        if hasattr(self, 'helpdesk_ticket_id') and self.helpdesk_ticket_id:
            self.helpdesk_ticket_id.invoice_ids |= refund
            message = _('Refund created')
            subtype_id = self.env.ref('helpdesk_account.mt_ticket_refund_created').id
            refund.message_post_with_source(
                'helpdesk.ticket_creation',
                render_values={'self': refund, 'ticket': self.helpdesk_ticket_id},
                subtype_id=subtype_id,
            )
            self.helpdesk_ticket_id.message_post_with_source(
                'helpdesk.ticket_conversion_link',
                render_values={'created_record': refund, 'message': message},
                subtype_id=subtype_id,
            )
    
        return refund


class HelpdeskTag(models.Model):
    _inherit = 'helpdesk.tag'

    related_ticket = fields.Many2one('helpdesk.ticket.type',string='Ticket relacionado')


class Helpdesk(models.Model):
    _inherit = 'helpdesk.ticket'

    quality_check_ids = fields.One2many(
        'quality.alert',
        'helpdesk_ticket_id',
        string='Alertas de Calidad'
    )
    

class QualityCheck(models.Model):
    _inherit = 'quality.alert'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket',
        string='Ticket de Soporte'
    )

