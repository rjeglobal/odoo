# Manufacturing Order Quoted State Implementation

This implementation adds a "Quoted" state to Manufacturing Orders with automatic sub-MO creation in quoted state.

## Module Structure

```bash
mrp_quoted_state/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── mrp_production.py
├── views/
│   └── mrp_production_views.xml
└── security/
    └── ir.model.access.csv
```

## 1. Module Manifest

```python
# mrp_quoted_state/__manifest__.py
{
    'name': 'Manufacturing Order Quoted State',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Add Quoted state to Manufacturing Orders for capacity planning',
    'description': """
        This module adds a 'Quoted' state to Manufacturing Orders:
        - Quoted state sits between Draft and Confirmed
        - Allows capacity planning without confirming orders
        - Automatically creates quoted sub-MOs for components
        - Can skip quoted state and go directly to confirmed
    """,
    'author': 'Your Company',
    'depends': ['mrp'],
    'data': [
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
}
```

## 2. Init Files

```python
# mrp_quoted_state/__init__.py
from . import models
```

```python
# mrp_quoted_state/models/__init__.py
from . import mrp_production
```

## 3. Model Extension

```python
# mrp_quoted_state/models/mrp_production.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    # Override the state field to add 'quoted' state
    state = fields.Selection(
        selection_add=[
            ('draft', 'Draft'),
            ('quoted', 'Quoted'),  # New state
            ('confirmed', 'Confirmed'),
        ],
        ondelete={
            'quoted': 'set draft',
        }
    )
    
    # Add field to track if this is a quoted sub-MO
    is_quoted_child = fields.Boolean(
        string='Is Quoted Child MO',
        copy=False,
        help='Indicates if this MO was created as a quoted sub-MO'
    )
    
    def action_quote(self):
        """
        Move MO from Draft to Quoted state and create quoted sub-MOs
        """
        if self.filtered(lambda mo: mo.state not in ['draft', 'cancel']):
            raise UserError(_('Only draft manufacturing orders can be quoted.'))
        
        for production in self:
            # Set to quoted state
            production.state = 'quoted'
            
            # Create sub-MOs in quoted state
            production._create_quoted_sub_mos()
            
            # Log the action
            production.message_post(
                body=_('Manufacturing Order has been quoted.')
            )
        
        return True
    
    def _create_quoted_sub_mos(self):
        """
        Create sub-MOs for manufactured components in quoted state
        """
        self.ensure_one()
        
        # Get all BOM lines that are manufactured products
        for line in self.bom_id.bom_line_ids:
            if line.product_id.bom_ids and line.product_id.type in ['product', 'consu']:
                # Calculate required quantity
                qty_to_produce = (line.product_qty / self.bom_id.product_qty) * self.product_qty
                
                # Find the BOM for this component
                bom = self.env['mrp.bom']._bom_find(
                    line.product_id,
                    bom_type='normal',
                    company_id=self.company_id.id
                )[line.product_id]
                
                if bom:
                    # Create the sub-MO
                    sub_mo_vals = {
                        'product_id': line.product_id.id,
                        'product_qty': qty_to_produce,
                        'product_uom_id': line.product_uom_id.id,
                        'bom_id': bom.id,
                        'date_start': self.date_start,
                        'date_deadline': self.date_start,  # Sub-MOs should complete before main MO
                        'origin': self.name,
                        'state': 'quoted',  # Create in quoted state
                        'is_quoted_child': True,
                        'company_id': self.company_id.id,
                        'procurement_group_id': self.procurement_group_id.id,
                        'propagate_cancel': self.propagate_cancel,
                        'move_dest_ids': [(4, move.id) for move in self.move_raw_ids.filtered(
                            lambda m: m.product_id == line.product_id
                        )],
                    }
                    
                    sub_mo = self.create(sub_mo_vals)
                    
                    # Recursively create quoted sub-MOs for the sub-MO
                    sub_mo._create_quoted_sub_mos()
    
    def action_confirm(self):
        """
        Override to handle both draft->confirmed and quoted->confirmed transitions
        """
        # Filter records by their current state
        draft_orders = self.filtered(lambda mo: mo.state == 'draft')
        quoted_orders = self.filtered(lambda mo: mo.state == 'quoted')
        
        # For draft orders going directly to confirmed, use standard behavior
        if draft_orders:
            super(MrpProduction, draft_orders).action_confirm()
        
        # For quoted orders, we need special handling
        if quoted_orders:
            # First, confirm all child quoted MOs
            for production in quoted_orders:
                child_mos = self.search([
                    ('origin', '=', production.name),
                    ('is_quoted_child', '=', True),
                    ('state', '=', 'quoted')
                ])
                if child_mos:
                    child_mos.action_confirm()
            
            # Then confirm the quoted orders using standard behavior
            # But first temporarily set them to draft so the standard method works
            quoted_orders.write({'state': 'draft'})
            super(MrpProduction, quoted_orders).action_confirm()
        
        return True
    
    def action_cancel(self):
        """
        Override to handle cancellation of quoted MOs
        """
        # Cancel any quoted child MOs
        for production in self.filtered(lambda mo: mo.state == 'quoted'):
            child_mos = self.search([
                ('origin', '=', production.name),
                ('is_quoted_child', '=', True),
                ('state', '=', 'quoted')
            ])
            if child_mos:
                child_mos.action_cancel()
        
        return super(MrpProduction, self).action_cancel()
    
    @api.model
    def _get_capacity_planning_domain(self):
        """
        Override this method if you have capacity planning reports
        to include quoted MOs
        """
        domain = super()._get_capacity_planning_domain()
        # Include quoted state in capacity planning
        if ('state', 'in', ['confirmed', 'progress', 'to_close']) in domain:
            index = domain.index(('state', 'in', ['confirmed', 'progress', 'to_close']))
            domain[index] = ('state', 'in', ['quoted', 'confirmed', 'progress', 'to_close'])
        return domain
    
    def _compute_reserved_availability(self):
        """
        Override to prevent reservation for quoted MOs
        """
        quoted_mos = self.filtered(lambda mo: mo.state == 'quoted')
        other_mos = self - quoted_mos
        
        # For quoted MOs, set reserved availability to 0
        for production in quoted_mos:
            production.reserved_availability = 0.0
        
        # For other MOs, use standard computation
        if other_mos:
            super(MrpProduction, other_mos)._compute_reserved_availability()
```

## 4. View Modifications

```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- mrp_quoted_state/views/mrp_production_views.xml -->
<odoo>
    <!-- Modify form view to add Quote button and show quoted state -->
    <record id="mrp_production_form_view_quoted_state" model="ir.ui.view">
        <field name="name">mrp.production.form.quoted.state</field>
        <field name="model">mrp.production</field>
        <field name="inherit_id" ref="mrp.mrp_production_form_view"/>
        <field name="arch" type="xml">
            <!-- Add Quote button in draft state -->
            <xpath expr="//button[@name='action_confirm']" position="before">
                <button name="action_quote" 
                        string="Create Quote" 
                        type="object" 
                        class="oe_highlight"
                        invisible="state != 'draft'"
                        help="Create a quoted MO for capacity planning"/>
            </xpath>
            
            <!-- Modify Confirm button to show in both draft and quoted states -->
            <xpath expr="//button[@name='action_confirm']" position="attributes">
                <attribute name="invisible">state not in ['draft', 'quoted']</attribute>
                <attribute name="string">Confirm Production</attribute>
            </xpath>
            
            <!-- Add badge/label for quoted child MOs -->
            <xpath expr="//div[@name='button_box']" position="inside">
                <button class="oe_stat_button" invisible="not is_quoted_child">
                    <div class="o_field_widget o_stat_info">
                        <span class="o_stat_text text-warning">Quoted Sub-MO</span>
                    </div>
                </button>
            </xpath>
            
            <!-- Update statusbar to show quoted state -->
            <xpath expr="//field[@name='state']" position="attributes">
                <attribute name="statusbar_visible">draft,quoted,confirmed,progress,done</attribute>
            </xpath>
        </field>
    </record>

    <!-- Add quoted state to tree view with distinctive color -->
    <record id="mrp_production_tree_view_quoted_state" model="ir.ui.view">
        <field name="name">mrp.production.tree.quoted.state</field>
        <field name="model">mrp.production</field>
        <field name="inherit_id" ref="mrp.mrp_production_tree_view"/>
        <field name="arch" type="xml">
            <!-- Add decoration for quoted state -->
            <xpath expr="//tree" position="attributes">
                <attribute name="decoration-info">state == 'quoted'</attribute>
            </xpath>
            
            <!-- Optionally add is_quoted_child field to tree -->
            <xpath expr="//field[@name='state']" position="after">
                <field name="is_quoted_child" optional="hide"/>
            </xpath>
        </field>
    </record>

    <!-- Add filter for quoted state in search view -->
    <record id="mrp_production_search_view_quoted_state" model="ir.ui.view">
        <field name="name">mrp.production.search.quoted.state</field>
        <field name="model">mrp.production</field>
        <field name="inherit_id" ref="mrp.view_mrp_production_filter"/>
        <field name="arch" type="xml">
            <!-- Add quoted filter -->
            <xpath expr="//filter[@name='confirmed']" position="after">
                <filter string="Quoted" 
                        name="quoted" 
                        domain="[('state', '=', 'quoted')]"
                        help="Quoted Manufacturing Orders"/>
            </xpath>
            
            <!-- Add filter for quoted child MOs -->
            <xpath expr="//filter[@name='late']" position="after">
                <separator/>
                <filter string="Quoted Sub-MOs" 
                        name="quoted_children" 
                        domain="[('is_quoted_child', '=', True)]"
                        help="Manufacturing Orders created as quoted sub-orders"/>
            </xpath>
            
            <!-- Add group by quoted state -->
            <xpath expr="//group" position="inside">
                <filter string="Quoted Status" 
                        name="groupby_quoted" 
                        domain="[]" 
                        context="{'group_by': 'is_quoted_child'}"/>
            </xpath>
        </field>
    </record>

    <!-- Modify kanban view to show quoted state -->
    <record id="mrp_production_kanban_view_quoted_state" model="ir.ui.view">
        <field name="name">mrp.production.kanban.quoted.state</field>
        <field name="model">mrp.production</field>
        <field name="inherit_id" ref="mrp.mrp_production_kanban_view"/>
        <field name="arch" type="xml">
            <!-- Add quoted state to kanban cards -->
            <xpath expr="//kanban" position="inside">
                <field name="is_quoted_child"/>
            </xpath>
            
            <!-- You may need to adjust this XPath based on actual kanban structure -->
            <xpath expr="//div[hasclass('oe_kanban_content')]" position="inside">
                <div t-if="record.state.raw_value == 'quoted'" class="text-info">
                    <i class="fa fa-clock-o"/> Quoted
                </div>
                <div t-if="record.is_quoted_child.raw_value" class="text-warning">
                    <small><i class="fa fa-link"/> Sub-MO</small>
                </div>
            </xpath>
        </field>
    </record>
</odoo>
```

## 5. Testing Scenarios

### Test 1: Create Quoted MO
1. Create new Manufacturing Order
2. Click "Create Quote" button
3. Verify state changes to "Quoted"
4. Check that sub-MOs are created in quoted state

### Test 2: Direct Confirmation
1. Create new Manufacturing Order
2. Click "Confirm Production" directly
3. Verify it skips quoted state

### Test 3: Quote to Confirm
1. Create quoted MO with sub-MOs
2. Click "Confirm Production"
3. Verify all quoted sub-MOs are also confirmed

### Test 4: Capacity Planning
1. Create several quoted MOs
2. Check capacity planning reports include them
3. Verify no inventory is reserved

## Important Considerations

1. **Inventory**: Quoted MOs don't reserve materials - they're planning only
2. **Cascading**: When confirming a quoted parent MO, all quoted sub-MOs confirm automatically
3. **Cancellation**: Canceling a quoted parent MO cancels its quoted sub-MOs
4. **Reports**: You may need to update capacity planning reports to include quoted state
5. **Scheduling**: Quoted MOs appear in planning but don't block resources
