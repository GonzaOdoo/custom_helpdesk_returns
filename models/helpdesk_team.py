from odoo import _, api, fields, models
import logging

_logger = logging.getLogger(__name__)
class HelpdeskTeam(models.Model):
    _inherit = 'helpdesk.team'

    next_team_id = fields.Many2one(
        'helpdesk.team',
        string='Siguiente equipo'
    )

    use_defect_routing = fields.Boolean(
        string='Derivar por defecto'
    )
    return_stage_id = fields.Many2one(
        'helpdesk.stage',
        string='Stage al regresar',
        help="Stage al que debe enviarse el ticket cuando vuelva a este equipo.",
        domain="[('team_ids', 'in', next_team_id)]",
    )
    conditional_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo condicional',
        domain="[('model', '=', 'helpdesk.ticket'), ('ttype', '=', 'boolean')]"
    )

    conditional_stage_id = fields.Many2one(
        'helpdesk.stage',
        string='Stage si TRUE',
        help="Stage al que se enviará si el campo condicional es verdadero."
    )

class HelpdeskStage(models.Model):
    _inherit = 'helpdesk.stage'

    auto_route = fields.Boolean(
        string="Redirigir ticket",
        help="If enabled, the ticket will be automatically routed to another team."
    )