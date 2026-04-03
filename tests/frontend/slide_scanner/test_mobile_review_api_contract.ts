import {
  slideScannerApi,
  type MobileHandoffResponse,
  type MobileRemoteDeleteResponse,
  type MobileReviewUpdateResponse
} from '../../../frontend/src/lib/api/slide-scanner';

type Assert<T extends true> = T;
type IsExact<A, B> =
  (<T>() => T extends A ? 1 : 2) extends
  (<T>() => T extends B ? 1 : 2) ? true : false;

type ApprovePayload = Awaited<ReturnType<typeof slideScannerApi.approveMobileItem>>;
type RejectPayload = Awaited<ReturnType<typeof slideScannerApi.rejectMobileItem>>;
type RemoteDeletePayload = Awaited<ReturnType<typeof slideScannerApi.remoteDeleteMobileItem>>;
type HandoffPayload = Awaited<ReturnType<typeof slideScannerApi.handoffMobileItem>>;

type _approveContract = Assert<IsExact<ApprovePayload, MobileReviewUpdateResponse>>;
type _rejectContract = Assert<IsExact<RejectPayload, MobileReviewUpdateResponse>>;
type _deleteContract = Assert<IsExact<RemoteDeletePayload, MobileRemoteDeleteResponse>>;
type _handoffContract = Assert<IsExact<HandoffPayload, MobileHandoffResponse>>;

const approvePayloadExample: ApprovePayload = { id: 1, approval_status: 'APPROVED' };
const rejectPayloadExample: RejectPayload = { id: 2, approval_status: 'REJECTED', reason: 'blurred' };
const deletePayloadExample: RemoteDeletePayload = {
  status: 'done',
  item_id: 3,
  results: {
    '/sdcard/DCIM/Camera/IMG_0001.jpg': true
  }
};
const handoffPayloadExample: HandoffPayload = {
  item_id: 3,
  slide_id: 91,
  slide_url: '/api/v1/ss/slides/91'
};

void approvePayloadExample;
void rejectPayloadExample;
void deletePayloadExample;
void handoffPayloadExample;

export {};
