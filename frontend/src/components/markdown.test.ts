import { describe, expect, it } from 'vitest'

import { plainText } from './Markdown'

describe('plainText', () => {
  it('reads Markdown as plain text for card previews', () => {
    const md = '## Status\n\n**Not ready** yet. See [the program](https://x.example/ME1A1).\n\n| Check | Result |\n|---|---|\n| Tokens | PASS |\n\n- one\n- `two`'
    expect(plainText(md)).toBe('Status\n\nNot ready yet. See the program.\n\nCheck · Result\nTokens · PASS\n\none\ntwo')
  })
})
