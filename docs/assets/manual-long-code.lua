-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) The CivicCast Authors
--
-- Long inline code is otherwise emitted as an unbreakable \texttt span. Use
-- url.sty's breakable path form for long values in prose and table cells.
-- Keep headers and figure captions untouched: LaTeX writes them to the table
-- of contents/list of figures, where url's active-character handling is not
-- safe in a moving argument.
local function breakable_windows_path(path)
  -- url.sty's \path does not treat Windows backslashes as break points. Keep
  -- the visible separators but allow TeX to wrap after each one.
  local pieces = {}
  for index = 1, #path do
    local char = path:sub(index, index)
    if char == "\\" then
      pieces[#pieces + 1] = "\\textbackslash{}\\hspace{0pt}"
    elseif char == "^" then
      pieces[#pieces + 1] = "\\textasciicircum{}"
    elseif char == "~" then
      pieces[#pieces + 1] = "\\textasciitilde{}"
    elseif char == "_" then
      pieces[#pieces + 1] = "\\_\\hspace{0pt}"
    elseif char == "." or char == "-" then
      pieces[#pieces + 1] = char .. "\\hspace{0pt}"
    elseif char:match("[#$%%&_{}]") then
      pieces[#pieces + 1] = "\\" .. char
    else
      pieces[#pieces + 1] = char
    end
  end
  return pandoc.RawInline("latex", "\\texttt{" .. table.concat(pieces) .. "}")
end

local function break_long_code(code)
  if code.text:find("[%w_.%-]+\\[%w_.%-]+") then
    return breakable_windows_path(code.text)
  end
  if code.text:find("%s") then
    -- url.sty's \path treats spaces as separators to discard. Preserve the
    -- spaces in commands while making each separator a legal wrap point.
    local pieces = {}
    local word = {}
    local replacements = {
      ["\\"] = "\\textbackslash{}",
      ["#"] = "\\#",
      ["$"] = "\\$",
      ["%"] = "\\%",
      ["&"] = "\\&",
      ["_"] = "\\_",
      ["{"] = "\\{",
      ["}"] = "\\}",
      ["^"] = "\\textasciicircum{}",
      ["~"] = "\\textasciitilde{}",
    }
    local function flush_word()
      if #word == 0 then
        return
      end
      local encoded = {}
      for _, char in ipairs(word) do
        encoded[#encoded + 1] = replacements[char] or char
        if char:match("[-._/:=]") then
          encoded[#encoded + 1] = "\\allowbreak{}"
        end
      end
      pieces[#pieces + 1] = "\\texttt{" .. table.concat(encoded) .. "}"
      word = {}
    end
    for index = 1, #code.text do
      local char = code.text:sub(index, index)
      if char:match("%s") then
        flush_word()
        pieces[#pieces + 1] = "\\hspace{0.5em}\\allowbreak"
      else
        word[#word + 1] = char
      end
    end
    flush_word()
    return pandoc.RawInline("latex", table.concat(pieces))
  end
  if #code.text >= 24 then
    return pandoc.RawInline("latex", "\\path{" .. code.text .. "}")
  end
end

local function break_bare_windows_path(text_node)
  local text = text_node.text
  local first, last = text:find("[%w_.%-]+\\[%w_.%-]+\\[%w_.%-]+")
  if not first then
    return
  end
  while first > 1 and text:sub(first - 1, first - 1):match("[%w_.%-]") do
    first = first - 1
  end
  while last < #text and text:sub(last + 1, last + 1):match("[%w_.%-\\]") do
    last = last + 1
  end
  while last >= first and text:sub(last, last) == "." do
    last = last - 1
  end
  local path = text:sub(first, last)
  if #path < 24 then
    return
  end
  local pieces = {}
  if first > 1 then
    pieces[#pieces + 1] = pandoc.Str(text:sub(1, first - 1))
  end
  pieces[#pieces + 1] = breakable_windows_path(path)
  if last < #text then
    pieces[#pieces + 1] = pandoc.Str(text:sub(last + 1))
  end
  return pieces
end

function Pandoc(doc)
  for index, block in ipairs(doc.blocks) do
    if block.t ~= "Figure" and block.t ~= "Header" then
      doc.blocks[index] = pandoc.walk_block(block, {
        Code = break_long_code,
        Str = break_bare_windows_path,
      })
    end
  end
  return doc
end
