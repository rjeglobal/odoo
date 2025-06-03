# Manufacturing Order Quoted State Module

## Overview

The **Manufacturing Order Quoted State** module adds a new "Quoted" state to manufacturing orders in Odoo. This functionality allows users to create manufacturing orders that can be quoted for capacity planning without confirming them. The module automatically generates sub-manufacturing orders (sub-MOs) in the quoted state for components, providing a flexible approach to managing production processes.

## Features

- Introduces a "Quoted" state for manufacturing orders.
- Allows for capacity planning without the need to confirm orders.
- Automatically creates quoted sub-MOs for components.
- Supports direct confirmation of manufacturing orders, bypassing the quoted state if desired.
- Provides user interface modifications to facilitate the quoting process.

## Installation Instructions

1. **Clone the repository** or download the module files.
2. Place the `mrp_quoted_state` directory in your Odoo addons path.
3. Update the app list in Odoo.
4. Install the **Manufacturing Order Quoted State** module from the Odoo apps interface.

## Testing Scenarios

- **Create Quoted MO**: Verify that a new manufacturing order can be created and quoted successfully.
- **Direct Confirmation**: Ensure that manufacturing orders can be confirmed directly, skipping the quoted state.
- **Quote to Confirm**: Check that quoted manufacturing orders and their sub-MOs can be confirmed together.
- **Capacity Planning**: Validate that quoted manufacturing orders are included in capacity planning reports without reserving inventory.

## Important Considerations

- Quoted manufacturing orders do not reserve materials; they are for planning purposes only.
- Confirming a quoted parent manufacturing order will automatically confirm all associated quoted sub-MOs.
- Canceling a quoted parent manufacturing order will also cancel its quoted sub-MOs.
- Capacity planning reports may need to be updated to include the new quoted state.
- Quoted manufacturing orders will appear in planning but will not block resources.