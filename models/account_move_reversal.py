# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools.translate import _
from odoo.exceptions import UserError
from odoo.tools import email_normalize, is_html_empty, html_escape, html2plaintext, parse_contact_from_email
import logging

_logger = logging.getLogger(__name__)
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


    @api.depends('l10n_latam_document_type_id', 'journal_id')
    def _compute_l10n_latam_manual_document_number(self):
        self.l10n_latam_manual_document_number = False
        for wiz in self.filtered(lambda x: x.journal_id and x.journal_id.l10n_latam_use_documents):
            if wiz.move_ids:
                wiz.l10n_latam_manual_document_number = self.env['account.move'].new({
                    'move_type': wiz._reverse_type_map(wiz.move_ids[0].move_type),
                    'journal_id': wiz.journal_id.id,
                    'partner_id': wiz.move_ids[0].partner_id.id,
                    'company_id': wiz.move_ids[0].company_id.id,
                    'reversed_entry_id': wiz.move_ids[0].id,
                })._is_manual_document_number()
            else:
                 wiz.l10n_latam_manual_document_number = self.env['account.move'].new({
                    'move_type': 'in_refund',
                    'journal_id': wiz.journal_id.id,
                    'partner_id': wiz.helpdesk_ticket_id.partner_id,
                    'company_id': wiz.company_id or (wiz.move_ids and wiz.move_ids[0].company_id) or wiz.env.company,
                    #'reversed_entry_id': wiz.move_ids[0].id,
                })._is_manual_document_number()

    @api.depends('move_ids', 'journal_id')
    def _compute_documents_info(self):
        self.l10n_latam_available_document_type_ids = False
        self.l10n_latam_use_documents = False
        for record in self:
            if len(record.move_ids) > 1:
                move_ids_use_document = record.move_ids._origin.filtered(lambda move: move.l10n_latam_use_documents)
                if move_ids_use_document:
                    raise UserError(_('You can only reverse documents with legal invoicing documents from Latin America one at a time.\nProblematic documents: %s', ", ".join(move_ids_use_document.mapped('name'))))
            else:
                record.l10n_latam_use_documents = record.journal_id.l10n_latam_use_documents
            if record.move_ids:
                if record.l10n_latam_use_documents:
                    refund = record.env['account.move'].new({
                        'move_type': record._reverse_type_map(record.move_ids.move_type),
                        'journal_id': record.journal_id.id,
                        'partner_id': record.move_ids.partner_id.id,
                        'company_id': record.move_ids.company_id.id,
                        'reversed_entry_id': record.move_ids.id,
                    })
                    record.l10n_latam_available_document_type_ids = refund.l10n_latam_available_document_type_ids
            else:
                if record.l10n_latam_use_documents:
                    refund = record.env['account.move'].new({
                        'move_type': 'in_refund',
                        'journal_id': record.journal_id.id,
                        'partner_id': record.helpdesk_ticket_id.partner_id,
                        'company_id': record.company_id or (record.move_ids and record.move_ids[0].company_id) or record.env.company,
                        #'reversed_entry_id': record.move_ids.id,
                    })
                    record.l10n_latam_available_document_type_ids = refund.l10n_latam_available_document_type_ids

    
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

class Defecto(models.Model):
    _name = 'helpdesk.sector.defect'
    name = fields.Char(string='Defecto')
    sector = fields.Many2one('hr.department',string='Sector a cargo')

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
    defect_type = fields.Many2one('helpdesk.sector.defect',string='Tipo de defecto')
    sector_in_charge = fields.Many2one('hr.department',string='Sector a cargo',related='defect_type.sector')

    component_product_id = fields.Many2one(
        'product.product',
        string="Componente a reparar",
        domain="[('id', 'in', suitable_component_ids)]",
        tracking=True
    )
    
    suitable_component_ids = fields.Many2many(
        'product.product',
        compute="_compute_suitable_component_ids",
        string="Componentes disponibles"
    )
    component_price = fields.Float('Precio de venta',related='component_product_id.lst_price')
    component_line_ids = fields.One2many(
        'helpdesk.ticket.component',
        'helpdesk_ticket_id',
        string='Componentes'
    )
    component_total_value = fields.Float(
        string="Total Componentes",
        compute="_compute_component_total_value",
        store=True
    )
    component_cost = fields.Float(
        string="Costo",
        compute="_compute_component_cost",
        store=True
    )


    @api.depends('component_line_ids.subtotal')
    def _compute_component_total_value(self):
        for ticket in self:
            ticket.component_total_value = sum(
                ticket.component_line_ids.mapped('subtotal')
            )
    @api.depends('component_line_ids.cost','component_line_ids.quantity')
    def _compute_component_cost(self):
        for ticket in self:
            ticket.component_cost = sum(
                ticket.component_line_ids.mapped('subtotal_cost')
            )
    

    def _get_default_dolar_value(self):
        usd = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        return usd.inverse_rate if usd else 0.0
    
    dolar_value = fields.Float(
        string="Valor dólar",
        default=_get_default_dolar_value,

    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for rec in self:
            if rec.product_id:
                rec.component_line_ids = [(5, 0, 0)]
    
    @api.depends('product_id')
    def _compute_suitable_component_ids(self):
        for ticket in self:
            if not ticket.product_id:
                ticket.suitable_component_ids = False
                continue
    
            component_ids = self._get_all_bom_components(
                ticket.product_id,
                ticket.company_id
            )
    
            ticket.suitable_component_ids = [fields.Command.set(list(component_ids))]


    def _get_product_attribute_value_ids(self, product):
        return set(product.product_template_attribute_value_ids.mapped('product_attribute_value_id').ids)
        
    def _get_all_bom_components(self, product, company, visited=None, root_attrs=None):
        """Devuelve todos los componentes recursivos filtrados por atributos"""
        if visited is None:
            visited = set()
    
        if root_attrs is None:
            root_attrs = self._get_product_attribute_value_ids(product)
    
        components = set()
    
        if product.id in visited:
            return components
    
        visited.add(product.id)
    
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('company_id', 'in', [False, company.id]),
        ], limit=1)
    
        if not bom:
            return components
    
        for line in bom.bom_line_ids:
            comp = line.product_id
            if not comp:
                continue
    
            # 🎯 Obtener atributos del componente
            comp_attrs = self._get_product_attribute_value_ids(comp)
    
            # 🔥 Filtro: solo si coinciden
            if comp_attrs and comp_attrs != root_attrs:
                continue
    
            components.add(comp.id)
    
            # 🔁 Recursión
            sub_components = self._get_all_bom_components(
                comp,
                company,
                visited,
                root_attrs
            )
            components.update(sub_components)
    
        return components

    @api.onchange('suitable_component_ids')
    def _onchange_component_product_id(self):
        if self.component_product_id not in self.suitable_component_ids:
            self.component_product_id = False

    def action_open_return_wizard_fixed(self):
        self.ensure_one()
    
        return {
            'type': 'ir.actions.act_window',
            'name': 'Return Picking',
            'res_model': 'stock.return.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                #'default_picking_id': self.picking_id.id,
                'default_fixed_product_id': self.product_id.id,
                'default_ticket_id':self.id,
            }
        }

    @api.depends('partner_id.email')
    def _compute_partner_email(self):
        for ticket in self:
            if ticket.partner_id:
                ticket.partner_email = ticket.partner_id.support_email

    def _inverse_partner_email(self):
        for ticket in self:
            if ticket._get_partner_email_update():
                ticket.partner_id.support_email = ticket.partner_email

    def _get_partner_email_update(self):
        self.ensure_one()
        if self.partner_id.support_email and self.partner_email != self.partner_id.support_email:
            ticket_email_normalized = email_normalize(self.partner_email) or self.partner_email or False
            partner_email_normalized = email_normalize(self.partner_id.support_email) or self.partner_id.support_email or False
            return ticket_email_normalized != partner_email_normalized
        return False
        
    def _message_get_suggested_recipients(self):
        recipients = super(Helpdesk, self)._message_get_suggested_recipients()
        try:
            for ticket in self:
                if ticket.partner_id and ticket.partner_id.support_email:
                    ticket._message_add_suggested_recipient(recipients, partner=ticket.partner_id, reason=_('Customer'))
                elif ticket.partner_email:
                    ticket._message_add_suggested_recipient(recipients, email=ticket.partner_email, reason=_('Customer Email'))
        except AccessError:  # no read access rights -> just ignore suggested recipients because this implies modifying followers
            pass
        return recipients

    def _message_add_suggested_recipient(self, result, partner=None, email=None, lang=None, reason=''):
        """ Called by _message_get_suggested_recipients, to add a suggested
            recipient in the result dictionary. The form is :
                partner_id, partner_name<partner_email> or partner_name, lang,
                reason, create_values """
        self.ensure_one()
        partner_info = {}
        _logger.info("Add recipient!")
        _logger.info(email)
        if email and not partner:
            # get partner info from email
            partner_info = self._message_partner_info_from_emails([email])[0]
            if partner_info.get('partner_id'):
                partner = self.env['res.partner'].sudo().browse([partner_info['partner_id']])[0]
        if email and email in [val[1] for val in result[self.ids[0]]]:  # already existing email -> skip
            return result
        if partner and partner in self.message_partner_ids:  # recipient already in the followers -> skip
            return result
        if partner and partner.id in [val[0] for val in result[self.ids[0]]]:  # already existing partner ID -> skip
            return result
        if partner and partner.support_email:  # complete profile: id, name <email>
            result[self.ids[0]].append((partner.id, partner.support_email, lang, reason, {}))
        elif partner:  # incomplete profile: id, name
            result[self.ids[0]].append((partner.id, partner.name or '', lang, reason, {}))
        else:  # unknown partner, we are probably managing an email address
            _, parsed_email_normalized = parse_contact_from_email(email)
            partner_create_values = self._get_customer_information().get(parsed_email_normalized, {})
            result[self.ids[0]].append((False, partner_info.get('full_name') or email, lang, reason, partner_create_values))
        return result

    def _notify_by_email_get_final_mail_values(self, recipient_ids, mail_values, additional_values=None):
        res = super()._notify_by_email_get_final_mail_values(
            recipient_ids, mail_values, additional_values
        )
    
        partners = self.env['res.partner'].browse(recipient_ids)
    
        emails = []
        for p in partners:
            email = p.support_email or p.email
            if email:
                _logger.info(email)
                emails.append(email)
    
        if emails:
            res['email_to'] = ','.join(emails)
            res.pop('recipient_ids', None)
    
        return res

    def _notify_get_recipients(self, message, msg_vals=None, **kwargs):
        recipients = super()._notify_get_recipients(
            message,
            msg_vals=msg_vals,
            **kwargs
        )
    
        for recipient in recipients:
            partner = recipient.get('partner')
            if partner and partner.support_email:
                recipient['email'] = partner.support_email
    
        return recipients

class QualityCheck(models.Model):
    _inherit = 'quality.alert'

    helpdesk_ticket_id = fields.Many2one(
        'helpdesk.ticket',
        string='Ticket de Soporte'
    )

