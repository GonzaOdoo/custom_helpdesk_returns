from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_round
import logging

_logger = logging.getLogger(__name__)
class ReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    return_type = fields.Selection(selection=[('full','Producto'),('item','Componentes')], string='Tipo de devolución',default='full',required=True)
    allowed_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_product_ids',
        string="Productos permitidos para devolución"
    )


    def _create_returns(self):
        selected_lines = self.product_return_moves.filtered('selected')
        _logger.info(selected_lines)
        for return_move in selected_lines.mapped('move_id'):
            return_move.move_dest_ids.filtered(lambda m: m.state not in ('done', 'cancel'))._do_unreserve()

        # create new picking for returned products
        new_picking = self.picking_id.copy(self._prepare_picking_default_values())
        picking_type_id = new_picking.picking_type_id.id
        new_picking.message_post_with_source(
            'mail.message_origin_link',
            render_values={'self': new_picking, 'origin': self.picking_id},
            subtype_xmlid='mail.mt_note',
        )
        returned_lines = 0
        for return_line in selected_lines:
            if not return_line.move_id:
                raise UserError(_("You have manually created product lines, please delete them to proceed."))
            if not float_is_zero(return_line.quantity, precision_rounding=return_line.uom_id.rounding):
                returned_lines += 1
                vals = self._prepare_move_default_values(return_line, new_picking)
                r = return_line.move_id.copy(vals)
                vals = {}

                # +--------------------------------------------------------------------------------------------------------+
                # |       picking_pick     <--Move Orig--    picking_pack     --Move Dest-->   picking_ship
                # |              | returned_move_ids              ↑                                  | returned_move_ids
                # |              ↓                                | return_line.move_id              ↓
                # |       return pick(Add as dest)          return toLink                    return ship(Add as orig)
                # +--------------------------------------------------------------------------------------------------------+
                move_orig_to_link = return_line.move_id.move_dest_ids.mapped('returned_move_ids')
                # link to original move
                move_orig_to_link |= return_line.move_id
                # link to siblings of original move, if any
                move_orig_to_link |= return_line.move_id\
                    .mapped('move_dest_ids').filtered(lambda m: m.state not in ('cancel'))\
                    .mapped('move_orig_ids').filtered(lambda m: m.state not in ('cancel'))
                move_dest_to_link = return_line.move_id.move_orig_ids.mapped('returned_move_ids')
                # link to children of originally returned moves, if any. Note that the use of
                # 'return_line.move_id.move_orig_ids.returned_move_ids.move_orig_ids.move_dest_ids'
                # instead of 'return_line.move_id.move_orig_ids.move_dest_ids' prevents linking a
                # return directly to the destination moves of its parents. However, the return of
                # the return will be linked to the destination moves.
                move_dest_to_link |= return_line.move_id.move_orig_ids.mapped('returned_move_ids')\
                    .mapped('move_orig_ids').filtered(lambda m: m.state not in ('cancel'))\
                    .mapped('move_dest_ids').filtered(lambda m: m.state not in ('cancel'))
                vals['move_orig_ids'] = [(4, m.id) for m in move_orig_to_link]
                vals['move_dest_ids'] = [(4, m.id) for m in move_dest_to_link]
                r.write(vals)
        if not returned_lines:
            raise UserError(_("Please specify at least one non-zero quantity."))

        new_picking.action_confirm()
        new_picking.action_assign()
        return new_picking.id, picking_type_id

    @api.depends('picking_id','return_type')
    def _compute_moves_locations(self):
        for wizard in self:
            move_dest_exists = False
            product_return_moves = [(5,)]  # limpia líneas existentes
            if wizard.picking_id and wizard.picking_id.state != 'done':
                raise UserError(_("You may only return Done pickings."))

            # Plantilla de valores por defecto para las líneas
            line_fields = [f for f in self.env['stock.return.picking.line']._fields.keys()]
            product_return_moves_data_tmpl = self.env['stock.return.picking.line'].default_get(line_fields)

            for move in wizard.picking_id.move_ids:
                if move.state == 'cancel' or move.scrapped:
                    continue
                if move.move_dest_ids:
                    move_dest_exists = True

                if wizard.return_type == 'item':
                    # ─── Devolución por COMPONENTES ───────────────────────
                    component_lines = wizard._get_component_return_lines(move, product_return_moves_data_tmpl)
                    product_return_moves.extend(component_lines)
                else:
                    # ─── Devolución normal (producto completo) ───────────
                    product_return_moves_data = dict(product_return_moves_data_tmpl)
                    product_return_moves_data.update(
                        wizard._prepare_stock_return_picking_line_vals_from_move(move)
                    )
                    product_return_moves.append((0, 0, product_return_moves_data))

            if wizard.picking_id and not product_return_moves:
                raise UserError(_("No products to return (only lines in Done state and not fully returned yet can be returned)."))

            if wizard.picking_id:
                wizard.product_return_moves = product_return_moves
                wizard.move_dest_exists = move_dest_exists
                wizard.parent_location_id = (
                    wizard.picking_id.picking_type_id.warehouse_id
                    and wizard.picking_id.picking_type_id.warehouse_id.view_location_id.id
                    or wizard.picking_id.location_id.location_id.id
                )
                wizard.original_location_id = wizard.picking_id.location_id.id
                location_id = wizard.picking_id.location_id.id
                if (
                    wizard.picking_id.picking_type_id.return_picking_type_id
                    and wizard.picking_id.picking_type_id.return_picking_type_id.default_location_dest_id.return_location
                ):
                    location_id = wizard.picking_id.picking_type_id.return_picking_type_id.default_location_dest_id.id
                wizard.location_id = (
                    wizard.picking_id.picking_type_id.default_location_return_id.id or location_id
                )


    @api.model
    def _prepare_stock_return_picking_line_vals_from_move(self, stock_move, return_type='full'):
        return_type = self.return_type
        if return_type == 'item':
            _logger.info('Nuevo metodo')
            # Obtener el BOM para el producto
            _logger.info(stock_move.product_tmpl_id.name)
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', stock_move.product_tmpl_id.id),
            ], limit=1)
            _logger.info(bom)
            if bom:
                _logger.info(bom)
                # Calcular la cantidad total disponible para devolver (igual que antes)
                quantity_to_return = stock_move.quantity
                for move in stock_move.move_dest_ids:
                    if not move.origin_returned_move_id or move.origin_returned_move_id != stock_move:
                        continue
                    quantity_to_return -= move.quantity
                quantity_to_return = float_round(
                    quantity_to_return,
                    precision_rounding=stock_move.product_id.uom_id.rounding
                )
    
                # Convertir a la unidad base si es necesario
                factor = stock_move.product_uom._compute_quantity(quantity_to_return, stock_move.product_id.uom_id)
    
                # Devolver líneas de componentes
                lines = []
                for bom_line in bom.bom_line_ids:
                    # Cantidad proporcional del componente
                    comp_qty = bom_line.product_qty * factor
                    lines.append({
                        'product_id': bom_line.product_id.id,
                        'quantity': comp_qty,
                        'move_id': stock_move.id,  # o podrías usar False si no aplica
                        'uom_id': bom_line.product_uom_id.id or bom_line.product_id.uom_id.id,
                    })
                return lines  # Nota: ahora devuelve una lista de dicts
    
        # Comportamiento normal (return_type == 'full' o no definido)
        quantity = stock_move.quantity
        for move in stock_move.move_dest_ids:
            if not move.origin_returned_move_id or move.origin_returned_move_id != stock_move:
                continue
            quantity -= move.quantity
        quantity = float_round(quantity, precision_rounding=stock_move.product_id.uom_id.rounding)
        return {
            'product_id': stock_move.product_id.id,
            'quantity': quantity,
            'move_id': stock_move.id,}




    def _get_component_return_lines(self, stock_move, default_vals_tmpl):
        """Devuelve una lista de comandos Odoo (0, 0, vals) para líneas de componentes."""
        # Buscar BOM aplicable (phantom es típico para kits)
        _logger.info(stock_move.product_id.product_template_variant_value_ids)
        bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', stock_move.product_tmpl_id.id),
            ], limit=1)
        if not bom:
            # Si no hay BOM, devolver el producto original como fallback
            vals = dict(default_vals_tmpl)
            vals.update(self._prepare_stock_return_picking_line_vals_from_move(stock_move))
            return [(0, 0, vals)]

        # Calcular cantidad neta a devolver
        quantity_to_return = stock_move.quantity
        for dest_move in stock_move.move_dest_ids:
            if not dest_move.origin_returned_move_id or dest_move.origin_returned_move_id != stock_move:
                continue
            quantity_to_return -= dest_move.quantity
        quantity_to_return = float_round(
            quantity_to_return,
            precision_rounding=stock_move.product_id.uom_id.rounding
        )

        # Asegurar conversión a la UoM base del producto
        factor = stock_move.product_uom._compute_quantity(
            quantity_to_return,
            stock_move.product_id.uom_id,
            rounding_method='HALF-UP'
        )

        lines = []
        for bom_line in bom.bom_line_ids:
            if not bom_line.bom_product_template_attribute_value_ids or bom_line.bom_product_template_attribute_value_ids in stock_move.product_id.product_template_variant_value_ids:
                comp_qty = bom_line.product_qty * factor
                vals = dict(default_vals_tmpl)
                vals.update({
                    'product_id': bom_line.product_id.id,
                    'quantity': comp_qty,
                    'move_id': stock_move.id,
                    'uom_id': bom_line.product_uom_id.id or bom_line.product_id.uom_id.id,
                })
                lines.append((0, 0, vals))
        return lines

    @api.depends('picking_id', 'return_type','product_return_moves','product_return_moves.product_id')
    def _compute_allowed_product_ids(self):
        for wizard in self:
            if not wizard.picking_id:
                wizard.allowed_product_ids = False
                continue
    
            # Productos inicialmente permitidos según lógica de devolución
            all_allowed_ids = set(wizard._get_allowed_product_ids())
            
            # Productos ya usados en las líneas actuales
            used_product_ids = set(wizard.product_return_moves.mapped('product_id.id'))
            _logger.info('Used')
            _logger.info(used_product_ids)
            # Permitidos = todos los válidos menos los ya usados
            available_ids = list(all_allowed_ids - used_product_ids)
            
            wizard.allowed_product_ids = [(6, 0, available_ids)]

    def _get_allowed_product_ids(self):
        """
        Devuelve una lista de IDs de productos permitidos para devolución,
        según el picking_id y return_type del wizard actual.
        """
        self.ensure_one()
        if not self.picking_id:
            return []
    
        product_ids = set()
    
        for move in self.picking_id.move_ids:
            if move.state == 'cancel' or move.scrapped:
                continue
    
            if self.return_type == 'item':
                # Buscar BOM del producto
                bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', move.product_tmpl_id.id),
                ], limit=1)
    
                if bom:
                    # Agregar todos los componentes del BOM
                    for bom_line in bom.bom_line_ids:
                        # Opcional: filtrar por atributos (como en _get_component_return_lines)
                        if not bom_line.bom_product_template_attribute_value_ids or \
                           bom_line.bom_product_template_attribute_value_ids in move.product_id.product_template_variant_value_ids:
                            product_ids.add(bom_line.product_id.id)
                else:
                    # Si no hay BOM, incluir el producto original como fallback
                    product_ids.add(move.product_id.id)
            else:
                # Modo 'full': producto completo
                product_ids.add(move.product_id.id)
    
        return list(product_ids)

    @api.onchange('product_return_moves')
    def _onchange_product_return_moves(self):
        # Esto fuerza la actualización de allowed_product_ids en la UI
        self._compute_allowed_product_ids()


class ReturnPickingLine(models.TransientModel):
    _inherit = "stock.return.picking.line"

    product_id = fields.Many2one(
        'product.product',
        string="Product",
        required=True,
        # Dominio dinámico basado en contexto
        domain=[]
    )
    product_cost = fields.Float(string='Costo',related='product_id.standard_price')

    selected = fields.Boolean(string='Seleccionado')

    @api.onchange('product_id')
    def _onchange_product_id_set_move_id(self):
        if self.product_id and not self.move_id and self.wizard_id and self.wizard_id.picking_id:
            picking = self.wizard_id.picking_id
    
            if self.wizard_id.return_type == 'full':
                # Buscar el move original del producto
                move = picking.move_ids.filtered(
                    lambda m: m.product_id == self.product_id and m.state == 'done' and not m.scrapped
                )
                if move:
                    self.move_id = move[0].id  # toma el primero si hay varios
    
            elif self.wizard_id.return_type == 'item':
                # En modo componente: buscar un move cuyo producto tenga un BOM que incluya este componente
                for move in picking.move_ids:
                    if move.state != 'done' or move.scrapped:
                        continue
                    bom = self.env['mrp.bom']._bom_find(products=move.product_id).get(move.product_id)
                    if bom and self.product_id in bom.bom_line_ids.product_id:
                        self.move_id = move.id
                        break
           