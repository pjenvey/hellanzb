require File.dirname(__FILE__) + '/../test_helper'
require 'live_controller'

# Re-raise errors caught by the controller.
class LiveController; def rescue_action(e) raise e end; end

class LiveControllerTest < Test::Unit::TestCase
  def setup
    @controller = LiveController.new
    @request    = ActionController::TestRequest.new
    @response   = ActionController::TestResponse.new
  end

  # Replace this with your real tests.
  def test_truth
    assert true
  end
end
