-- ~/.config/nvim/lua/custom/chadrc.lua
-- This is the main entry point for user customizations.
-- This file is automatically loaded by NvChad.

local M = {}

-- NvChad uses the 'formatter.nvim' plugin, which is a wrapper around conform.nvim.
-- We can configure it here.
M.plugins = {
  ["formatter"] = {
    -- Enable format on save
    format_on_save = {
      -- These options will be passed to conform.format()
      timeout_ms = 500,
      lsp_fallback = true, -- Use LSP formatting if no formatter is found
    },
    
    -- Define formatters for different file types.
    -- You need to ensure the formatter executable (e.g., 'black') is installed
    -- and available in your system's PATH.
    formatters_by_ft = {
      python = { "black" }, -- Use the 'black' formatter for python files
      
      -- You can add other file types here, for example:
      -- lua = { "stylua" },
      -- javascript = { "prettier" },
      -- typescript = { "prettier" },
      -- go = { "gofmt", "goimports" },
    },
  },
}

return M
