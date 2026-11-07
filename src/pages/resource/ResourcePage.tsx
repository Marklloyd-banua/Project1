import type { ChangeEvent, FormEvent } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import type { BaseRecord } from '../../types/models'
import { deletePlatformRecord, listPlatformRecords, savePlatformRecord, setPlatformRecordStatus } from '../../services/dataRepository'
import { PageHeader } from '../../components/common/PageHeader'
import { StatusBadge } from '../../components/common/StatusBadge'
import { Modal } from '../../components/common/Modal'
import { useApp } from '../../contexts/AppContext'
import { toApiError } from '../../services/api/errorHandler'
import { createCsv, parseCsv } from '../../utils/csv'

interface ResourceRow extends BaseRecord {
  id: string
  name: string
  status: string
  [key: string]: string | number | boolean
}

const config = {
  // ... rest of existing config object ...
}

export function ResourcePage() {
  // ... existing component code until row rendering ...

  {rows.map((row: unknown) => {
    const safeRow = row as ResourceRow
    return (
      <tr key={safeRow.id}>
        {columnKeys.map(key => (
          <td key={key}>
            {key === 'status' ? (
              <StatusBadge status={String(safeRow[key])} />
            ) : key === 'id' ? (
              <strong className="record-id">{display(safeRow[key])}</strong>
            ) : key === 'amount' || key === 'mrr' || key === 'monthly' || key === 'annual' ? (
              `$${Number(safeRow[key]).toLocaleString()}`
            ) : (
              display(safeRow[key])
            )}
          </td>
        ))}
        {/* ... rest of existing row rendering ... */}
      </tr>
    )
  })}

  // ... rest of existing component code ...
}
