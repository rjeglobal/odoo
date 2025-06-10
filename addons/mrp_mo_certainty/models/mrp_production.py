from odoo import models, fields, api, _

class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    certainty = fields.Selection([
        ('0', '0%'),
        ('25', '25%'),
        ('50', '50%'),
        ('75', '75%'),
        ('100', '100%')
    ], string='Certainty', 
       default='25',
       tracking=True,
       help='Probability or confidence level of this manufacturing order')
    
    # Optional: Add a computed field to show certainty as a percentage number
    certainty_percentage = fields.Integer(
        string='Certainty %',
        compute='_compute_certainty_percentage',
        store=True
    )
    
    @api.depends('certainty')
    def _compute_certainty_percentage(self):
        """Convert certainty selection to integer percentage"""
        for production in self:
            if production.certainty:
                production.certainty_percentage = int(production.certainty)
            else:
                production.certainty_percentage = 0
    
    def action_confirm(self):
        """Override to set certainty to 100% when MO is confirmed"""
        # Set certainty to 100% for all MOs being confirmed
        self.write({'certainty': '100'})
        
        # Update child MOs certainty to 100% as well
        self._update_child_mos_certainty('100')
        
        # Call the parent method
        return super(MrpProduction, self).action_confirm()
    
    def action_cancel(self):
        """Override to set certainty to 0% when MO is cancelled"""
        # Set certainty to 0% for all MOs being cancelled
        self.write({'certainty': '0'})
        
        # Update child MOs certainty to 0% as well
        self._update_child_mos_certainty('0')
        
        # Call the parent method
        return super(MrpProduction, self).action_cancel()
    
    def write(self, vals):
        """Override to propagate certainty changes to child MOs"""
        res = super(MrpProduction, self).write(vals)
        
        # If certainty is updated, update all child MOs
        if 'certainty' in vals:
            self._update_child_mos_certainty(vals['certainty'])
        
        return res
    
    def _update_child_mos_certainty(self, certainty_value):
        """Update certainty for all child MOs"""
        for production in self:
            # Find child MOs via parent_production_id
            child_mos = self.search([
                ('parent_production_id', '=', production.id),
                ('state', 'not in', ['done', 'cancel'])  # Don't update done/cancelled MOs
            ])
            
            # Find child MOs via origin
            origin_child_mos = self.search([
                ('origin', '=', production.name),
                ('id', '!=', production.id),
                ('state', 'not in', ['done', 'cancel'])
            ])
            
            # Combine and update
            all_child_mos = child_mos | origin_child_mos
            if all_child_mos:
                all_child_mos.write({'certainty': certainty_value})
                production.message_post(
                    body=_('Updated certainty to %s%% on %d child MO(s)') % (
                        certainty_value, len(all_child_mos)
                    )
                )
    
    @api.model
    def create(self, vals):
        """Override to ensure MOs inherit parent's certainty"""
        # If creating a child MO (has origin or parent_production_id)
        if vals.get('origin') or vals.get('parent_production_id'):
            parent_mo = False
            
            # Try to find parent by parent_production_id first
            if vals.get('parent_production_id'):
                parent_mo = self.browse(vals['parent_production_id'])
            # Otherwise try by origin
            elif vals.get('origin'):
                parent_mo = self.search([
                    ('name', '=', vals['origin']),
                    ('company_id', '=', vals.get('company_id', self.env.company.id))
                ], limit=1)
            
            # If parent found and certainty not specified, inherit parent's certainty
            if parent_mo and 'certainty' not in vals:
                vals['certainty'] = parent_mo.certainty
        
        # For quoted MOs without parent, default to 25%
        elif vals.get('state') == 'quoted' and 'certainty' not in vals:
            vals['certainty'] = '25'
        
        return super(MrpProduction, self).create(vals)