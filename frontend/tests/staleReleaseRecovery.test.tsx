import './dom-environment.ts'
import {afterEach,test} from 'node:test'
import assert from 'node:assert/strict'
import React,{lazy,Suspense} from 'react'
import {cleanup,render,waitFor} from '@testing-library/react'
import {ErrorBoundary} from '../src/components/ui/ErrorBoundary'

afterEach(cleanup)
test('an old tab with a missing lazy chunk fails safely and a fresh application mount recovers',async()=>{
 const OldChunk=lazy(async()=>{throw new Error('Synthetic unavailable old release chunk; diagnostic must stay hidden')})
 const view=render(<ErrorBoundary key="old-release"><Suspense fallback={<p>Loading chunk</p>}><OldChunk/></Suspense></ErrorBoundary>)
 await waitFor(()=>assert.ok(view.getByRole('alert')))
 assert.ok(view.getByRole('button',{name:'Reload PowerFlow'}))
 assert.ok(view.getByText(/retrieve the current application files/))
 assert.equal(view.queryByText(/diagnostic must stay hidden/),null)
 // A full reload creates a new boundary and retrieves current index/assets.
 // No browser reload or network request is performed by this isolated test.
 view.rerender(<ErrorBoundary key="new-release"><h1>Current release loaded</h1></ErrorBoundary>)
 assert.ok(view.getByRole('heading',{name:'Current release loaded'}))
 assert.equal(view.queryByRole('alert'),null)
})
