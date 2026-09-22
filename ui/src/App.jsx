import React, { useState, useEffect, useCallback } from 'react';
import './App.css';
import Header from './components/Header';
import CheckForm from './components/CheckForm';
import CheckPreview from './components/CheckPreview';
import LedgerTable from './components/LedgerTable';
import VoidModal from './components/VoidModal';
import DisclaimerModal from './components/DisclaimerModal';
import SettingsModal from './components/SettingsModal';

export default function App() {
  const [activeTab, setActiveTab] = useState('studio');
  const [accountInfo, setAccountInfo] = useState(null);
  const [checks, setChecks] = useState([]);
  const [isChecksLoading, setIsChecksLoading] = useState(false);

  // Form State
  const [formData, setFormData] = useState({
    account_id: 'ACC-001',
    check_number: 39254225,
    payee: 'BRANDON BACH',
    amount_dollars: 5000.0,
    issue_date: new Date().toISOString().split('T')[0],
    memo: 'Medical Payments to Others coverage',
    layout: 'remittance', // 'remittance' or 'standard'
    page_format: 'check_only', // 'check_only' or 'voucher_sheet'
    signature_name: 'Minnie Hinds',
    draw_signature: true,
    remittance_data: null,
    outline_only: false,
  });

  // Next sequential serial from DB
  const [nextSerial, setNextSerial] = useState(null);

  // Preview & Printing State
  const [previewData, setPreviewData] = useState(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);
  const [lastPrintResult, setLastPrintResult] = useState(null);

  // Void modal state
  const [voidCheckTarget, setVoidCheckTarget] = useState(null);
  const [isVoiding, setIsVoiding] = useState(false);

  // Legal Disclaimer modal state
  const [isDisclaimerOpen, setIsDisclaimerOpen] = useState(false);

  // Settings modal state
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const fetchNextSerial = useCallback(() => {
    fetch('/api/checks/next-serial')
      .then((res) => res.json())
      .then((data) => {
        if (data.next_serial) {
          setNextSerial(data.next_serial);
        }
      })
      .catch((err) => console.error('Failed to load next serial:', err));
  }, []);

  // 1. Initial Load: Accounts, Remittance Template, Checks, Next Serial
  useEffect(() => {
    fetch('/api/accounts')
      .then((res) => res.json())
      .then((data) => setAccountInfo(data))
      .catch((err) => console.error('Failed to load accounts:', err));

    fetch('/api/templates/remittance')
      .then((res) => res.json())
      .then((data) => {
        setFormData((prev) => ({
          ...prev,
          remittance_data: data,
        }));
      })
      .catch((err) => console.error('Failed to load remittance template:', err));

    fetchNextSerial();
    loadChecks();
  }, [fetchNextSerial]);

  // 2. Load Check History
  const loadChecks = () => {
    setIsChecksLoading(true);
    fetch('/api/checks')
      .then((res) => res.json())
      .then((data) => setChecks(data.checks || []))
      .catch((err) => console.error('Failed to load checks:', err))
      .finally(() => setIsChecksLoading(false));
  };

  // 3. Debounced Live Preview Generator
  useEffect(() => {
    if (!formData.payee || formData.amount_dollars <= 0) return;

    const timer = setTimeout(() => {
      setIsPreviewLoading(true);
      fetch('/api/checks/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      })
        .then((res) => {
          if (!res.ok) throw new Error('Preview error');
          return res.json();
        })
        .then((data) => {
          setPreviewData(data);
        })
        .catch((err) => console.error('Preview failed:', err))
        .finally(() => setIsPreviewLoading(false));
    }, 280);

    return () => clearTimeout(timer);
  }, [
    formData.check_number,
    formData.payee,
    formData.amount_dollars,
    formData.issue_date,
    formData.memo,
    formData.layout,
    formData.page_format,
    formData.signature_name,
    formData.remittance_data,
    formData.outline_only,
  ]);

  // 4. Print Check Execution
  const handlePrint = async () => {
    setIsPrinting(true);
    try {
      const res = await fetch('/api/checks/print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Issuance failed: ${err.detail || 'Unknown error'}`);
        return;
      }

      const result = await res.json();
      setLastPrintResult(result);
      loadChecks(); // Refresh registry
      fetchNextSerial(); // Refresh sequence counter
    } catch (err) {
      alert(`Issuance error: ${err.message}`);
    } finally {
      setIsPrinting(false);
    }
  };

  // 5. Void Check Execution
  const handleConfirmVoid = async (serial, reason) => {
    setIsVoiding(true);
    try {
      const res = await fetch(`/api/checks/${serial}/void`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Voiding failed: ${err.detail || 'Unknown error'}`);
        return;
      }

      setVoidCheckTarget(null);
      loadChecks();
    } catch (err) {
      alert(`Voiding error: ${err.message}`);
    } finally {
      setIsVoiding(false);
    }
  };

  return (
    <div className="app-container">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        accountInfo={accountInfo}
        onRefresh={loadChecks}
        onOpenDisclaimer={() => setIsDisclaimerOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* Persistent Legal Non-Liability Banner Strip */}
      <div className="legal-banner-strip">
        <div className="legal-banner-inner">
          <span className="legal-banner-icon">⚖️</span>
          <span className="legal-banner-text">
            <strong>DEVELOPER NON-LIABILITY DISCLAIMER:</strong> This software is provided strictly &quot;AS IS&quot; for technical evaluation. The developer assumes zero legal or financial liability for check issuance, bank negotiation, or losses. Operator assumes 100% legal responsibility under UCC Articles 3 &amp; 4.
          </span>
          <button
            type="button"
            className="legal-banner-btn"
            onClick={() => setIsDisclaimerOpen(true)}
          >
            Terms of Use
          </button>
        </div>
      </div>

      <main className="app-content">
        {activeTab === 'studio' ? (
          <div className="studio-grid">
            <CheckForm
              formData={formData}
              setFormData={setFormData}
              previewData={previewData}
              nextSerial={nextSerial}
              onPrint={handlePrint}
              isPrinting={isPrinting}
            />

            <CheckPreview
              previewData={previewData}
              isLoading={isPreviewLoading}
              lastPrintResult={lastPrintResult}
              onClearPrintResult={() => setLastPrintResult(null)}
            />
          </div>
        ) : (
          <LedgerTable
            checks={checks}
            isLoading={isChecksLoading}
            onRefresh={loadChecks}
            onOpenVoidModal={(check) => setVoidCheckTarget(check)}
          />
        )}
      </main>

      {/* Comprehensive Legal Non-Liability Footer */}
      <footer className="app-footer-disclaimer">
        <div className="footer-disclaimer-inner">
          <div className="footer-disclaimer-title">
            <span>⚖️</span>
            <strong>LEGAL DISCLAIMER &amp; COMPLETE DEVELOPER LIABILITY WAIVER</strong>
          </div>
          <p className="footer-disclaimer-text">
            THIS SOFTWARE IS PROVIDED &quot;AS IS&quot; AND WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. UNDER NO CIRCUMSTANCES SHALL THE DEVELOPER, AUTHORS, OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, PUNITIVE, OR CONSEQUENTIAL DAMAGES (INCLUDING BUT NOT LIMITED TO LOSS OF FUNDS, BANK FEES, RETURN CHECK CHARGES, REJECTIONS, OR LEGAL DISPUTES) ARISING FROM OR IN CONNECTION WITH THIS SOFTWARE OR ANY CHECKS GENERATED, PRINTED, OR NEGOTIATED HEREWITH. OPERATORS BEAR EXCLUSIVE RESPONSIBILITY FOR COMPLIANCE WITH APPLICABLE BANKING LAWS AND WRITTEN DEPOSIT AGREEMENTS.
          </p>
          <div className="footer-disclaimer-meta">
            <span>ANSI X9.100 Check Engine · Built for Technical Evaluation</span>
            <button
              type="button"
              className="footer-link-btn"
              onClick={() => setIsDisclaimerOpen(true)}
            >
              View Complete Disclaimer &amp; Terms
            </button>
          </div>
        </div>
      </footer>

      {/* Void Confirmation Modal */}
      {voidCheckTarget && (
        <VoidModal
          check={voidCheckTarget}
          onClose={() => setVoidCheckTarget(null)}
          onConfirmVoid={handleConfirmVoid}
          isVoiding={isVoiding}
        />
      )}

      {/* Developer Liability Disclaimer Modal */}
      {isDisclaimerOpen && (
        <DisclaimerModal onClose={() => setIsDisclaimerOpen(false)} />
      )}

      {/* Account & Routing Settings Modal */}
      {isSettingsOpen && (
        <SettingsModal
          accountInfo={accountInfo}
          onClose={() => setIsSettingsOpen(false)}
          onSaved={() => {
            // Reload account info after save
            fetch('/api/accounts').then(r => r.json()).then(setAccountInfo);
          }}
        />
      )}
    </div>
  );
}
