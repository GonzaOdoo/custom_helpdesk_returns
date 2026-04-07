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
    fixed_product_id = fields.Many2one(
        'product.product',
        string='Producto fijo'
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string="Tipo de operación",
        domain="[('code','=',operation_type)]"
    )
    operation_type = fields.Selection([
        ('incoming','Recepción'),
        ('outgoing','Entrega')
    ], string="Tipo", default='incoming')

    location_source_id = fields.Many2one(
        'stock.location',
        string='Ubicación de Origen',
        domain="[('usage', '!=', 'view')]"
    )
    
    location_dest_id = fields.Many2one(
        'stock.location',
        string='Ubicación de destino',
        domain="[('usage', '!=', 'view')]"
    )
    
    @api.onchange('picking_type_id')
    def _onchange_picking_type(self):
        if not self.picking_type_id:
            return
    
        customer_location = self.env['stock.location'].search(
            [('usage', '=', 'customer')],
            limit=1
        )
    
        self.location_source_id = (
            self.picking_type_id.default_location_src_id.id
            or customer_location.id
            or self.location_source_id
        )
    
        self.location_dest_id = (
            self.picking_type_id.default_location_dest_id.id
            or customer_location.id
            or self.location_dest_id
        )
        
    @api.onchange('operation_type')
    def _onchange_operation_type(self):
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', self.operation_type)
        ], limit=1)
    
        if picking_type:
            self.picking_type_id = picking_type

    @api.depends('picking_id')
    def _compute_sale_order_id(self):
        for r in self:
            r.sale_order_id = r.picking_id.sale_id

    @api.depends('sale_order_id')
    def _compute_picking_id(self):
        for r in self:
            _logger.info("Overwrite_picking")
            return False


    def _create_returns(self):
        selected_lines = self.product_return_moves.filtered('selected')
        
        if not selected_lines:
            raise UserError(_("Please select at least one product."))
            
        if not self.picking_id:
            customer_location = self.env['stock.location'].search(
                [('usage', '=', 'customer')],
                limit=1
            )
        
            location_id = (
                self.location_source_id.id
                or self.picking_type_id.default_location_src_id.id
            )
            
            location_dest_id = (
                self.location_dest_id.id
                or self.picking_type_id.default_location_dest_id.id
            )
            
            picking = self.env['stock.picking'].create({
                'partner_id': self.ticket_id.partner_id.id if self.ticket_id.partner_id else False,
                'picking_type_id': self.picking_type_id.id,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'origin': f'Ticket #{self.ticket_id.ticket_ref}' if self.ticket_id else '',
            })
        else:
            picking = self.picking_id.copy(self._prepare_picking_default_values())
            
        for line in selected_lines:
            self.env['stock.move'].create({
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
        picking.action_confirm()
        picking.action_assign()
    
        return picking.id, picking.picking_type_id.id

    @api.depends('picking_id','return_type','fixed_product_id')
    def _compute_moves_locations(self):
        for wizard in self:
            move_dest_exists = False
            product_return_moves = [(5,)]
    
            if wizard.picking_id and wizard.picking_id.state != 'done':
                raise UserError(_("You may only return Done pickings."))
    
            line_fields = [f for f in self.env['stock.return.picking.line']._fields.keys()]
            product_return_moves_data_tmpl = self.env['stock.return.picking.line'].default_get(line_fields)
    
            moves = wizard.picking_id.move_ids
    
            # ⭐ FILTRO PARA PRODUCTO FIJO
            if not moves and wizard.fixed_product_id:
                if wizard.return_type == 'item':
                    bom = self.env['mrp.bom']._bom_find(products=wizard.fixed_product_id).get(wizard.fixed_product_id)
                    if bom:
                        for line in bom.bom_line_ids:
                            product_return_moves_data = dict(product_return_moves_data_tmpl)
                            product_return_moves_data.update({
                                'product_id': line.product_id.id,
                                'quantity': line.product_qty,
                            })
                            product_return_moves.append((0, 0, product_return_moves_data))
                else:
                    product_return_moves_data = dict(product_return_moves_data_tmpl)
                    product_return_moves_data.update({
                        'product_id': wizard.fixed_product_id.id,
                        'quantity': 1,
                    })
                    product_return_moves.append((0, 0, product_return_moves_data))
            _logger.info("Moves!!!")
            _logger.info(moves)
            for move in moves:
                if move.state == 'cancel' or move.scrapped:
                    continue
    
                if move.move_dest_ids:
                    move_dest_exists = True
    
                if wizard.return_type == 'item':
                    component_lines = wizard._get_component_return_lines(move, product_return_moves_data_tmpl)
                    product_return_moves.extend(component_lines)
    
                else:
                    product_return_moves_data = dict(product_return_moves_data_tmpl)
                    product_return_moves_data.update(
                        wizard._prepare_stock_return_picking_line_vals_from_move(move)
                    )
                    product_return_moves.append((0, 0, product_return_moves_data))
    
            if wizard.picking_id and len(product_return_moves) <= 1:
                raise UserError(_("No products to return."))
    
            wizard.product_return_moves = product_return_moves

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
            #if not wizard.picking_id:
            #    wizard.allowed_product_ids = False
            #    continue
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
        _logger.info(self.fixed_product_id)
        if self.fixed_product_id:
            if self.return_type == 'full':
                _logger.info(self.fixed_product_id.id)
                return [self.fixed_product_id.id]
            elif self.return_type == 'item':
                bom = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', self.fixed_product_id.product_tmpl_id.id)
                ], limit=1)
    
                if bom:
                    _logger.info(bom.bom_line_ids.product_id.ids)
                    return bom.bom_line_ids.product_id.ids
                return []
    
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
           